"""Evaluate saved detections against manually labelled source-video goal times."""
import math


def seconds(value):
    if isinstance(value,bool):raise ValueError('Гол уақыты сан немесе HH:MM:SS болуы керек.')
    parts=str(value).strip().split(':')
    if not 1<=len(parts)<=3:raise ValueError('Уақыт пішімі: HH:MM:SS.')
    try:
        numbers=[float(p) for p in parts]
        if any(not math.isfinite(n) or n<0 for n in numbers):raise ValueError()
        if len(numbers)>1 and (any(n>=60 for n in numbers[1:]) or any(n!=int(n) for n in numbers[:-1])):raise ValueError()
    except ValueError:raise ValueError('Гол уақыты қате: '+str(value)) from None
    return sum(n*60**i for i,n in enumerate(reversed(numbers)))


def match_goals(expected,predicted,tolerance=12):
    """Maximum one-to-one matches, then minimum timestamp error; no double credit."""
    tolerance=float(tolerance)
    if not math.isfinite(tolerance) or tolerance<0:raise ValueError('Уақыт төзімділігі теріс болмауы керек.')
    truth=sorted(seconds(t) for t in expected);found=sorted(seconds(t) for t in predicted)
    if len(set(truth))!=len(truth):raise ValueError('Нақты гол уақыты қайталанған.')
    n,m=len(truth),len(found)
    scores=[[(0,0.) for _ in range(m+1)] for _ in range(n+1)]
    steps={}
    for i in range(1,n+1):
        for j in range(1,m+1):
            best=scores[i-1][j];action='truth'
            if scores[i][j-1]>best:best=scores[i][j-1];action='prediction'
            error=abs(truth[i-1]-found[j-1])
            if error<=tolerance:
                before=scores[i-1][j-1];candidate=(before[0]+1,before[1]-error)
                if candidate>=best:best=candidate;action='match'
            scores[i][j]=best;steps[i,j]=action
    i,j=n,m;matches=[];used_truth=set();used_found=set()
    while i and j:
        action=steps[i,j]
        if action=='match':
            matches.append(dict(actual=truth[i-1],detected=found[j-1],error_seconds=round(abs(truth[i-1]-found[j-1]),3)))
            used_truth.add(i-1);used_found.add(j-1);i-=1;j-=1
        elif action=='truth':i-=1
        else:j-=1
    tp=len(matches);fp=m-tp;fn=n-tp
    return dict(expected=n,detected=m,true_positives=tp,false_positives=fp,false_negatives=fn,
                precision=tp/m if m else None,recall=tp/n if n else None,
                f1=2*tp/(n+m) if n+m else None,tolerance_seconds=tolerance,
                matches=list(reversed(matches)),missed=[t for k,t in enumerate(truth) if k not in used_truth],
                extra=[t for k,t in enumerate(found) if k not in used_found])


def evaluate_project(project,expected,tolerance=12):
    from core import confirmed_goal_candidates
    analysis=project.get('analysis')
    if not isinstance(analysis,dict):raise ValueError('Жобада сақталған талдау табылмады. Видеоны қайта талдаңыз.')
    truth=[seconds(t) for t in expected]
    duration=analysis.get('info',{}).get('duration')
    if duration is not None and any(t>float(duration) for t in truth):raise ValueError('Гол уақыты бастапқы видео ұзақтығынан асып тұр.')
    source='detected_goals' if 'detected_goals' in analysis else 'score_events_fallback'
    candidates=analysis.get('detected_goals') if source=='detected_goals' else confirmed_goal_candidates(analysis.get('score_events',[]))
    predicted=[max(0,float(c['goal_at'])) for c in candidates]
    detection=match_goals(truth,predicted,tolerance)
    clips=project.get('clips',analysis.get('clips',[]))
    retained=[t for t in sorted(truth) if any(float(c['start'])<=t<float(c['end']) for c in clips)]
    return dict(prediction_source=source,detection=detection,
                selection=dict(retained_goal_times=retained,missing_goal_times=[t for t in sorted(truth) if t not in retained],
                               coverage=len(retained)/len(truth) if truth else None),
                ignored_score_states=analysis.get('ignored_score_states',[]))
