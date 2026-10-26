"""Bounded, content-addressed raw snapshots and a resumable request cache.

Cache keys include public URL/params; private parameters and auth headers are redacted from request metadata and errors.
Refresh explicitly to obtain a new snapshot. Raw bytes are never overwritten.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import threading
from urllib.parse import urlsplit,quote,quote_plus
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class Store:
    _host_times={}
    _rate_lock=threading.Lock()
    def __init__(self, root='data', refresh=False, max_mb=80):
        self.root = Path(root)
        self.refresh = refresh
        self.max_bytes = int(max_mb * 1_000_000)
        self.last_record=None
        (self.root / 'raw').mkdir(parents=True, exist_ok=True)
        (self.root / 'cache').mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        retry = Retry(total=4, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], respect_retry_after_header=True)
        self.session.mount('https://', HTTPAdapter(max_retries=retry))
        self.session.headers.update({'User-Agent': 'LA-parking-foundation/0.1 public-data-research'})

    def get(self, url, params=None, *, headers=None, max_mb=None, secret_params=None, allow_html=False):
        key = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
        pointer = self.root / 'cache' / f'{key}.json'
        if pointer.exists() and not self.refresh:
            record = json.loads(pointer.read_text())
            path = self.root / record['path']
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256']:
                content_type=next((v for k,v in record.get('headers',{}).items() if k.lower()=='content-type'),'')
                if 'text/html' in content_type and not allow_html:raise ValueError('Cached HTML is not a usable data API response')
                self.last_record=record
                return path, record
        limit = int(max_mb * 1_000_000) if max_mb else self.max_bytes
        record = {'url': url, 'params': params, 'retrieved_at_utc': utcnow(), 'request_key': key}
        secrets=[str(v) for v in (secret_params or {}).values() if v]
        secrets += [str(v) for k,v in (headers or {}).items() if k.lower() in ['authorization','x-app-token'] and v]
        def redact(value):
            if isinstance(value,dict):return {k:redact(v) for k,v in value.items()}
            if isinstance(value,list):return [redact(v) for v in value]
            if isinstance(value,str):
                for secret in secrets:
                    for representation in {secret,quote(secret,safe=''),quote_plus(secret)}:value=value.replace(representation,'REDACTED')
            return value
        tmp = self.root / 'raw' / f'{key}.partial'
        try:
            host=urlsplit(url).hostname or '';interval=1.0 if host=='data.lacity.org' else .25
            with self._rate_lock:
                delay=interval-(time.monotonic()-self._host_times.get(host,0))
                if delay>0:time.sleep(delay)
                self._host_times[host]=time.monotonic()
            with self.session.get(url, params={**(params or {}), **(secret_params or {})}, headers=headers, stream=True, timeout=(15, 90)) as r:
                record.update(status=r.status_code, final_url=redact(r.url), headers=redact(dict(r.headers)))
                r.raise_for_status()
                if int(r.headers.get('Content-Length', 0)) > limit:
                    raise ValueError('Advertised response exceeds byte budget')
                if 'text/html' in r.headers.get('Content-Type', '') and not allow_html:
                    raise ValueError('HTML is not a usable data API response')
                digest, size = hashlib.sha256(), 0
                with tmp.open('wb') as out:
                    for chunk in r.iter_content(256 * 1024):
                        size += len(chunk)
                        if size > limit:
                            raise ValueError('Response exceeds byte budget; no truncated export accepted')
                        out.write(chunk); digest.update(chunk)
                if r.headers.get('Content-Length') and not r.headers.get('Content-Encoding') and size != int(r.headers['Content-Length']):
                    raise ValueError('Incomplete response body')
                sha = digest.hexdigest()
                path = self.root / 'raw' / sha
                if path.exists():
                    if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
                        raise ValueError('Existing immutable raw snapshot is corrupt; inspect before recovery')
                    tmp.unlink()
                else:
                    tmp.rename(path)
                record.update(path=str(path.relative_to(self.root)), sha256=sha, bytes=size,
                              success=True, received_at_utc=utcnow())
                pointer.write_text(json.dumps(record, indent=2), encoding='utf8')
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            message=redact(str(exc))
            record.update(success=False, error=message)
            raise RuntimeError(message) from None
        finally:
            self.last_record=record
            with (self.root / 'manifest.jsonl').open('a', encoding='utf8') as f:
                f.write(json.dumps(record) + '\n')
            time.sleep(0.15)
        return path, record

    def json(self, url, params=None, **kwargs):
        path, rec = self.get(url, params, **kwargs)
        obj = json.loads(path.read_bytes())
        if isinstance(obj, dict) and ('error' in obj or obj.get('type') == 'error'):
            message=json.dumps(obj)
            for secret in (kwargs.get('secret_params') or {}).values():message=message.replace(str(secret),'REDACTED')
            raise ValueError('API error: '+message)
        return obj, rec
