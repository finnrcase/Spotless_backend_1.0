"""Bounded, content-addressed raw snapshots and a resumable request cache.

Cache keys include public URL/params; credentials go in headers, never manifests.
Refresh explicitly to obtain a new snapshot. Raw bytes are never overwritten.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root='data', refresh=False, max_mb=80):
        self.root = Path(root)
        self.refresh = refresh
        self.max_bytes = int(max_mb * 1_000_000)
        (self.root / 'raw').mkdir(parents=True, exist_ok=True)
        (self.root / 'cache').mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        retry = Retry(total=4, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], respect_retry_after_header=True)
        self.session.mount('https://', HTTPAdapter(max_retries=retry))
        self.session.headers.update({'User-Agent': 'LA-parking-foundation/0.1 public-data-research'})

    def get(self, url, params=None, *, headers=None, max_mb=None, secret_params=None):
        key = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
        pointer = self.root / 'cache' / f'{key}.json'
        if pointer.exists() and not self.refresh:
            record = json.loads(pointer.read_text())
            path = self.root / record['path']
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256']:
                return path, record
        limit = int(max_mb * 1_000_000) if max_mb else self.max_bytes
        record = {'url': url, 'params': params, 'retrieved_at_utc': utcnow(), 'request_key': key}
        tmp = self.root / 'raw' / f'{key}.partial'
        try:
            with self.session.get(url, params={**(params or {}), **(secret_params or {})}, headers=headers, stream=True, timeout=(15, 90)) as r:
                public_url=r.url
                for secret in (secret_params or {}).values():
                    public_url=public_url.replace(str(secret),'REDACTED')
                record.update(status=r.status_code, final_url=public_url, headers=dict(r.headers))
                r.raise_for_status()
                if int(r.headers.get('Content-Length', 0)) > limit:
                    raise ValueError('Advertised response exceeds byte budget')
                if 'text/html' in r.headers.get('Content-Type', ''):
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
                record.update(path=str(path.relative_to(self.root)), sha256=sha, bytes=size, success=True)
                pointer.write_text(json.dumps(record, indent=2), encoding='utf8')
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            message=str(exc)
            for secret in (secret_params or {}).values(): message=message.replace(str(secret),'REDACTED')
            record.update(success=False, error=message)
            raise RuntimeError(message) from None
        finally:
            with (self.root / 'manifest.jsonl').open('a', encoding='utf8') as f:
                f.write(json.dumps(record) + '\n')
            time.sleep(0.15)
        return path, record

    def json(self, url, params=None, **kwargs):
        path, rec = self.get(url, params, **kwargs)
        obj = json.loads(path.read_bytes())
        if isinstance(obj, dict) and ('error' in obj or obj.get('type') == 'error'):
            raise ValueError(f'API error: {obj}')
        return obj, rec
