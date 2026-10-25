"""Causal feature construction with a separate, explicit retrospective context tier."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
from sklearn.neighbors import BallTree
from .spatial import METRIC_CRS

CALENDAR=['hour_sin','hour_cos','weekday_sin','weekday_cos','weekend','month_sin','month_cos','holiday']
HISTORY=['lag_rate_15','lag_rate_30','lag_rate_60','lag_coverage','arrivals_60','departures_60','occupancy_week_ago','neighbor_rate_300','neighbor_rate_600','hour_x_lag']
CONTEXT=['buildings_100','buildings_300','buildings_600','business_100','business_300','business_600','food_retail_300','hydrants_100','driveways_100','context_x_weekend','current_price_midpoint','current_time_limit_hours']
HOLIDAYS={'2025-09-01'}  # Labor Day; no US federal August holiday. No parking exemption inferred.


def calendar_features(times):
    local=pd.to_datetime(times,utc=True).dt.tz_convert('America/Los_Angeles'); hour=local.dt.hour+local.dt.minute/60
    return pd.DataFrame({'hour_sin':np.sin(hour*2*np.pi/24),'hour_cos':np.cos(hour*2*np.pi/24),
        'weekday_sin':np.sin(local.dt.dayofweek*2*np.pi/7),'weekday_cos':np.cos(local.dt.dayofweek*2*np.pi/7),
        'weekend':local.dt.dayofweek.ge(5).astype(int),'month_sin':np.sin(local.dt.month*2*np.pi/12),'month_cos':np.cos(local.dt.month*2*np.pi/12),
        'holiday':local.dt.strftime('%Y-%m-%d').isin(HOLIDAYS).astype(int)},index=times.index)


def spatial_context():
    seg=gpd.read_parquet('data/processed/pilot_street_segments.parquet').to_crs(METRIC_CRS).set_index('segment_id')
    center=seg.geometry.interpolate(.5,normalized=True)
    context=pd.DataFrame(index=seg.index)
    layers={}
    for name in ['buildings','hydrants','driveways']:
        g=gpd.read_parquet(f'data/processed/pilot_{name}.parquet').to_crs(METRIC_CRS)
        layers[name]=g.loc[g.is_valid&~g.is_empty].geometry.representative_point()
    b=pd.read_parquet('data/staged/business.parquet'); valid=b.location_1.map(lambda d:isinstance(d,dict) and d.get('latitude') is not None)
    b=b.loc[valid].copy(); pts=gpd.GeoSeries(gpd.points_from_xy(b.location_1.map(lambda d:float(d['longitude'])),b.location_1.map(lambda d:float(d['latitude']))),crs=4326).to_crs(METRIC_CRS)
    layers['business']=pts; layers['food_retail']=pts.loc[b.naics.fillna('').str.startswith(('722','44','45')).to_numpy()]
    xy=np.c_[center.x,center.y]
    for name,points in layers.items():
        tree=BallTree(np.c_[points.x,points.y])
        scales=[100,300,600] if name in ['buildings','business'] else [300] if name=='food_retail' else [100]
        for radius in scales: context[f'{name}_{radius}']=tree.query_radius(xy,r=radius,count_only=True)
    mapping=pd.read_parquet('data/processed/meter_face_mapping.parquet').query("join_status=='matched'")
    meters=pd.read_parquet('data/processed/pilot_meters.parquet').drop(columns='geometry')
    m=meters.merge(mapping,left_on='spaceid',right_on='space_id')
    def price(value):
        import re
        vals=[float(x) for x in re.findall(r'\d+(?:\.\d+)?',str(value))]
        return float(np.mean(vals)) if vals else np.nan
    def limit(value):
        import re
        match=re.search(r'(\d+(?:\.\d+)?)',str(value))
        if not match: return np.nan
        return float(match[1])/(60 if 'MIN' in str(value).upper() else 1)
    m['current_price_midpoint']=m.raterange.map(price);m['current_time_limit_hours']=m.timelimit.map(limit)
    for name in ['current_price_midpoint','current_time_limit_hours']: context[name]=m.groupby('segment_id')[name].mean()
    lonlat=center.to_crs(4326)
    context['latitude']=lonlat.y;context['longitude']=lonlat.x;context['x']=center.x;context['y']=center.y
    context['area']=np.where(context.latitude.ge(34.0635),'Westwood pilot north','Westwood pilot south')
    context.reset_index().to_parquet('data/modeling/current_context.parquet',index=False)
    return context


def build_design(config_path='config/modeling.json'):
    cfg=json.loads(Path(config_path).read_text());p=Path('data/modeling');p.mkdir(exist_ok=True)
    panel=pd.read_parquet(p/'panel_intervals.parquet').sort_values(['source_month','block_face_id','interval_start_utc'])
    mapping=pd.read_parquet('data/processed/meter_face_mapping.parquet').query("join_status=='matched'")
    face_block=mapping[['block_face_id','segment_id']].drop_duplicates().set_index('block_face_id').segment_id
    panel['block_id']=panel.block_face_id.map(face_block)
    ctx=spatial_context();panel=panel.merge(ctx,left_on='block_id',right_index=True,validate='many_to_one')
    # Hold out the whole north area plus a metric buffer; masks use geometry only.
    holdout=ctx.latitude.ge(cfg['spatial_holdout_latitude_gte'])
    spatial_test=set(ctx.index[holdout]); test_xy=ctx.loc[holdout,['x','y']].to_numpy()
    dist=BallTree(test_xy).query(ctx[['x','y']].to_numpy(),k=1)[0][:,0]
    spatial_train=set(ctx.index[~holdout&(dist>cfg['spatial_buffer_m'])])
    (Path('reports/modeling')/'spatial_split.json').write_text(json.dumps({'test_blocks':sorted(spatial_test),'train_blocks':sorted(spatial_train),'buffer_m':cfg['spatial_buffer_m'],'area_definition':f"latitude >= {cfg['spatial_holdout_latitude_gte']}",'chosen_without_labels':True},indent=2))
    panel['spatial_role']=np.where(panel.block_id.isin(spatial_test),'test',np.where(panel.block_id.isin(spatial_train),'train','buffer'))
    panel['label_valid']=panel.coverage_fraction.ge(cfg['minimum_known_sensor_time_fraction'])
    # State persistence is already time weighted; only complete bins strictly before origin become features.
    group=panel.groupby(['source_month','block_face_id'],sort=False)
    for lag in [15,30,60]: panel[f'lag_rate_{lag}']=group.occupancy_rate.shift(lag//cfg['interval_minutes'])
    panel['lag_coverage']=group.coverage_fraction.shift(1)
    panel['occupancy_week_ago']=group.occupancy_rate.shift(7*24*60//cfg['interval_minutes'])
    for col in ['arrivals','departures']:
        panel[col+'_60']=group[col].transform(lambda x:x.shift(1).rolling(4,min_periods=1).sum())
    # Freeze contemporaneous neighbors from previous completed bins; no future target/coverage enters.
    neighbor_cols=[]
    for role in ['all','train_only']:
        for radius in [300,600]:
            col=f'neighbor_{role}_{radius}';panel[col]=np.nan;neighbor_cols.append(col)
            for month,pm in panel.groupby('source_month'):
                wide=pm.pivot(index='interval_start_utc',columns='block_face_id',values='lag_rate_15')
                block=pm.drop_duplicates('block_face_id').set_index('block_face_id').block_id.reindex(wide.columns)
                xy=ctx.loc[block,['x','y']].to_numpy(); d=np.linalg.norm(xy[:,None,:]-xy[None,:,:],axis=2)
                weights=(d<=radius)&(block.to_numpy()[:,None]!=block.to_numpy()[None,:])
                if role=='train_only': weights&=np.array([b in spatial_train for b in block])[None,:]
                a=wide.to_numpy();finite=np.isfinite(a)
                denom=finite.astype(float)@weights.T
                result=np.divide(np.nan_to_num(a)@weights.T,denom,out=np.full_like(a,np.nan),where=denom>0)
                long=pd.DataFrame(result,index=wide.index,columns=wide.columns).stack(future_stack=True).rename(col).reset_index()
                lookup=long.set_index(['interval_start_utc','block_face_id'])[col]
                ix=pd.MultiIndex.from_frame(pm[['interval_start_utc','block_face_id']]);panel.loc[pm.index,col]=lookup.reindex(ix).to_numpy()
    designs=[]
    for horizon in cfg['horizons_minutes']:
        rows=panel.copy();rows['issued_at_utc']=rows.interval_start_utc
        rows['arrival_time_utc']=rows.issued_at_utc+pd.Timedelta(minutes=horizon)
        target=panel[['source_month','block_face_id','interval_start_utc','occupancy_rate','coverage_fraction','panel_occupied_count','panel_available_count','panel_any_vacant','label_valid']].rename(columns={
            'interval_start_utc':'arrival_time_utc','occupancy_rate':'target_occupancy_rate','coverage_fraction':'target_coverage_fraction',
            'panel_occupied_count':'target_occupied_count','panel_available_count':'target_available_count','panel_any_vacant':'target_any_panel_vacant','label_valid':'target_valid'})
        rows=rows.merge(target,on=['source_month','block_face_id','arrival_time_utc'],how='left',validate='one_to_one')
        rows['horizon_minutes']=horizon
        cal=calendar_features(rows.arrival_time_utc)
        for c in CALENDAR: rows[c]=cal[c].to_numpy()
        rows['hour_x_lag']=rows.hour_sin*rows.lag_rate_15
        rows['context_x_weekend']=rows.business_300*rows.weekend
        rows['feature_event_time_utc']=rows.issued_at_utc
        rows['feature_available_at_utc']=rows.issued_at_utc
        rows['context_available_at_utc']=pd.Timestamp('2026-10-25T03:38:33.794603Z')
        rows['evidence_class']='retrospective_sensor_panel_proxy'
        # Invalid future coverage is retained as unsupported, not filled with zero occupancy.
        rows.loc[~rows.target_valid.fillna(False).astype(bool),'target_occupancy_rate']=np.nan
        designs.append(rows)
    result=pd.concat(designs,ignore_index=True)
    result.to_parquet(p/'design.parquet',index=False)
    catalog=[]
    for family,names,availability in [('calendar',CALENDAR,'deterministic at issue time'),('causal_sensor_history',HISTORY,'events <= issue time; immediate-delivery assumption'),('current_spatial_context',CONTEXT,'2026-10 snapshot; retrospective tier only')]:
        for name in names: catalog.append({'feature':name,'family':family,'event_effective_time':'origin history / requested arrival / source snapshot','availability':availability})
    missing={'housing_vehicle_ownership':'ACS blocked; no historical tract match','workplace_employment':'LODES acquired, no verified block-geography join','business_hours':'unverified/unavailable','events_attendance':'no supported attendance; calendar retrieved after backtest dates','restrictions_capacity':'unverified; unavailable','weather':'no historical issued forecasts for target periods','transit':'only October 2026 schedule snapshot','closures':'historical effective/availability timestamps unverified'}
    Path('reports/modeling/feature_catalog.json').write_text(json.dumps({'features':catalog,'excluded_families':missing,'geometry_vintage':'October 2026; all spatial assignment is retrospective'},indent=2))
    print('Design rows',len(result),'rate labels',int(result.target_occupancy_rate.notna().sum()),flush=True)
    return result
