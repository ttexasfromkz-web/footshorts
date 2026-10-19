"""Offline comparison of a saved project with hand-labelled source-video goals."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from goal_evaluation import evaluate_project


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project',type=Path,help='source/project.json')
    parser.add_argument('labels',type=Path,help='JSON: {"goals": ["01:18", "02:45"]}; source-video time, not match clock')
    parser.add_argument('--tolerance',type=float,default=12)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.output.resolve() in (args.project.resolve(),args.labels.resolve()):raise ValueError('Есепті бөлек файлға сақтаңыз.')
        project=json.loads(args.project.read_text(encoding='utf-8-sig'))
        labels=json.loads(args.labels.read_text(encoding='utf-8-sig'))
        if not isinstance(project,dict) or not isinstance(labels,dict):raise ValueError('Жоба мен белгі JSON объектісі болуы керек.')
        if not isinstance(labels.get('goals'),list):raise ValueError('goals тізімі қажет.')
        report=evaluate_project(project,labels['goals'],args.tolerance)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    except (OSError,ValueError,KeyError,TypeError) as e:parser.error(str(e))
    print(args.output)


if __name__=='__main__':main()
