"""Incremental, bounded acquisition. Run again to resume cached batches."""
import argparse
import json
from pathlib import Path
from .http import Store, utcnow
from .connectors import arcgis, socrata, download_month, census_acs
from .sources import NAV, SODA, DATASETS, PILOT


def save_json(path,obj):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2),encoding='utf8')


def run(months=(), refresh=False):
    store=Store(refresh=refresh)
    stage=Path('data/staged'); stage.mkdir(parents=True,exist_ok=True)
    results={}
    def attempt(name,fn):
        try:
            info=fn(); results[name]={'status':'verified/downloaded','result':info}
        except Exception as exc:
            results[name]={'status':'blocked','error':str(exc)}
            print(name,'FAILED',str(exc),flush=True)
        save_json('reports/acquisition_status.json',results)

    metadata={}
    for name,ident in DATASETS.items():
        def meta(name=name,ident=ident):
            obj,rec=store.json(f'{SODA}/api/views/{ident}.json')
            metadata[name]=obj; save_json(stage/f'{name}_metadata.json',obj)
            return {'retrieved_at_utc':rec['retrieved_at_utc'],'source_rows_updated_epoch':obj.get('rowsUpdatedAt'),'license':obj.get('license')}
        attempt(name+'_metadata',meta)

    def spatial(name,ident,bbox=None):
        budget=120000 if name=='streets' else (25000 if name=='curbs' else 15000)
        obj,meta,oid=arcgis(store,f'{NAV}/{ident}',bbox=bbox,max_features=budget)
        save_json(stage/f'{name}.geojson',obj); save_json(stage/f'{name}_metadata.json',meta)
        return {'features':len(obj['features']),'oid':oid,'scope':'citywide source' if bbox is None else list(bbox)}
    attempt('boundary',lambda:spatial('boundary',414))
    attempt('streets',lambda:spatial('streets',341))
    for name,ident in [('curbs',324),('driveways',325),('hydrants',107),('regulatory_signs',177),('bikeways',157),('red_curb',431),('buildings',393),('zoning',75),('construction',1),('construction_streets',212)]:
        attempt(name,lambda name=name,ident=ident:spatial(name,ident,PILOT))

    def table(name,where=None):
        frame=socrata(store,DATASETS[name],where=where)
        frame.to_parquet(stage/f'{name}.parquet',index=False)
        return {'rows':len(frame),'scope':where or 'complete export'}
    attempt('meters',lambda:table('meters'))
    attempt('occupancy',lambda:table('occupancy'))
    for name in ['sweeping','permits','signs']:
        attempt(name,lambda name=name:table(name))
    west,south,east,north=PILOT
    attempt('business',lambda:table('business',f'within_box(location_1,{north},{west},{south},{east})'))

    for month in months:
        def history(month=month):
            path,rec=download_month(store,metadata['history'],month)
            save_json(stage/f'history_{month}.json',{'path':str(path),'record':rec,'month':month})
            return {'path':str(path),'bytes':rec['bytes'],'month':month}
        attempt('history_'+month,history)

    def acs():
        frame=census_acs(store); frame.to_parquet(stage/'acs.parquet',index=False)
        return {'rows':len(frame),'vintage':2024,'scope':'Los Angeles County tracts'}
    attempt('acs',acs)
    # National Weather Service: free/public, UTC valid times, forecast generation retained.
    def forecast():
        point,_=store.json('https://api.weather.gov/points/34.0689,-118.4452')
        obj,rec=store.json(point['properties']['forecastHourly'])
        save_json(stage/'weather_forecast.json',obj)
        return {'periods':len(obj['properties']['periods']),'generatedAt':obj['properties'].get('generatedAt'),'retrieved_at_utc':rec['retrieved_at_utc']}
    attempt('weather_forecast',forecast)
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--months',nargs='*',default=[]); p.add_argument('--refresh',action='store_true')
    a=p.parse_args(); run(a.months,a.refresh)
