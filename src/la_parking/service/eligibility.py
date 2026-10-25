"""Conservative full-stay rule evaluation; absence of rules is not permission."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from .schemas import RestrictionRecord,RuleCoverage,EligibilityResult,EligibilityProfile

LA=ZoneInfo('America/Los_Angeles')
UTC=timezone.utc


def local_candidates(wall:datetime):
    if wall.tzinfo is not None:raise ValueError('Expected a local wall time without an offset')
    options={}
    for fold in [0,1]:
        aware=wall.replace(tzinfo=LA,fold=fold);value=aware.astimezone(UTC)
        if value.astimezone(LA).replace(tzinfo=None)==wall:options[value]=aware
    return sorted(options)


def resolve_local(wall_text:str,fold:int|None=None):
    wall=datetime.fromisoformat(wall_text)
    options=local_candidates(wall)
    if not options:raise ValueError('This local time does not exist during the DST spring transition')
    if len(options)>1 and fold is None:raise ValueError('Ambiguous DST local time; choose first occurrence (fold=0) or second (fold=1)')
    if fold not in [None,0,1]:raise ValueError('Fold must be 0 or 1')
    return options[fold or 0] if len(options)>1 else options[0]


def spans(rule:RestrictionRecord,start:datetime,end:datetime):
    start,end=start.astimezone(UTC),end.astimezone(UTC)
    if not rule.local_start:
        return [(max(start,rule.effective_from),min(end,rule.effective_to))],False
    output=[];ambiguous=False
    day=start.astimezone(LA).date()-timedelta(days=1)
    last=end.astimezone(LA).date()
    while day<=last:
        if rule.weekdays is None or day.weekday() in rule.weekdays:
            a=datetime.fromisoformat(f'{day.isoformat()}T{rule.local_start}')
            b=datetime.fromisoformat(f'{day.isoformat()}T{rule.local_end}')
            if b<=a:b+=timedelta(days=1)
            aa,bb=local_candidates(a),local_candidates(b)
            if len(aa)!=1 or len(bb)!=1:
                # A boundary in a DST fold/gap needs explicit official interpretation.
                ambiguous=True
            else:output.append((max(start,aa[0],rule.effective_from),min(end,bb[0],rule.effective_to)))
        day+=timedelta(days=1)
    return output,ambiguous


def evaluate(face_id,start,stay_minutes,profile,rules,coverage,as_of):
    start,as_of=start.astimezone(UTC),as_of.astimezone(UTC);end=start+timedelta(minutes=stay_minutes)
    profile=EligibilityProfile.model_validate(profile)
    records=[RestrictionRecord.model_validate(r) for r in rules if r['block_face_id']==face_id]
    records=[r for r in records if r.available_at<=as_of]
    cover=[RuleCoverage.model_validate(c) for c in coverage if c['block_face_id']==face_id]
    fresh_cover=[c for c in cover if c.complete and c.available_at<=as_of and c.verified_at<=as_of and c.expires_at>=max(end,as_of) and c.effective_from<=start and c.effective_to>=end]
    official=any(c.source_kind=='official' for c in fresh_cover);posted=any(c.source_kind=='posted_sign_review' for c in fresh_cover)
    denied=[];allowed=[];uncertain=[];details=[];upcoming=[]
    for rule in records:
        ranges,ambiguous=spans(rule,start,end)
        active=[(a,b) for a,b in ranges if b>a]
        is_fresh=rule.verification=='verified' and rule.verified_at is not None and rule.verified_at<=as_of and (rule.expires_at is None or rule.expires_at>=max(end,as_of))
        summary={'id':rule.restriction_id,'type':rule.rule_type,'raw_text':rule.raw_text,'source_kind':rule.source_kind,'source_url':rule.source_url,
                 'verification':rule.verification,'verified_at':rule.verified_at.isoformat() if rule.verified_at else None,'effective_from':rule.effective_from.isoformat(),'effective_to':rule.effective_to.isoformat(),'verification_current':is_fresh}
        future,_=spans(rule,start,end+timedelta(minutes=60))
        if any(b>a and a>=end for a,b in future):upcoming.append(summary)
        if ambiguous and rule.effective_from<end and rule.effective_to>start:uncertain.append(rule.restriction_id)
        if not active:continue
        details.append(summary)
        if not is_fresh:uncertain.append(rule.restriction_id);continue
        prohibits=rule.rule_type=='no_parking'
        if rule.rule_type=='permit':prohibits=profile.permit_class not in rule.allowed_permits
        if rule.rule_type=='vehicle_only':prohibits=profile.vehicle_class not in rule.allowed_vehicles
        if rule.rule_type=='max_duration':
            if rule.maximum_stay_minutes is None:uncertain.append(rule.restriction_id)
            else:prohibits=stay_minutes>rule.maximum_stay_minutes
        if prohibits:denied.extend(active)
        elif rule.rule_type=='allow':allowed.extend(active)
    conflict=any(a<d and c<b for a,b in denied for c,d in allowed)
    if conflict:status,reason='conflict','Verified rules conflict during the intended stay; source precedence needs review'
    elif denied:status,reason='prohibited','A verified restriction excludes this profile during part or all of the intended stay'
    elif uncertain:status,reason='unknown','Some applicable rules are stale, unreviewed or have unresolved DST schedule boundaries'
    elif official or posted:status,reason='allowed','Complete reviewed rule coverage supports this profile for the entire intended stay'
    else:status,reason='unknown','Complete current rule coverage is unavailable; missing signs do not mean unrestricted parking'
    return EligibilityResult(status=status,reason=reason,checked_from=start,checked_to=end,official_coverage_complete=official,posted_sign_coverage_complete=posted,restrictions=details,upcoming=upcoming)
