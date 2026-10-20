"""Call the service with JSON test input files and save responses as evidence."""
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("input", help="JSON file or folder containing JSON files")
    parser.add_argument("--output",default="./batch-output")
    parser.add_argument("--url",default="http://localhost:8000")
    args=parser.parse_args()
    source=Path(args.input); files=[source] if source.is_file() else sorted(source.glob("*.json"))
    output=Path(args.output); output.mkdir(parents=True,exist_ok=True)
    summary=[]
    for path in files:
        payload=json.loads(path.read_text(encoding="utf-8")); key=payload.pop("idempotency_key",path.stem)
        request=Request(args.url.rstrip("/")+"/api/v1/publish",data=json.dumps(payload).encode(),headers={"Content-Type":"application/json","Idempotency-Key":key},method="POST")
        try:
            with urlopen(request,timeout=30) as response:
                result={"http_status":response.status,"body":json.loads(response.read())}
        except HTTPError as exc:
            result={"http_status":exc.code,"body":json.loads(exc.read())}
        except URLError as exc:
            result={"http_status":None,"body":{"error":{"code":"PLATFORM_UNAVAILABLE","message":str(exc.reason),"retryable":True,"details":{}}}}
        result["input_file"]=str(path)
        (output/f"{path.stem}.result.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
        summary.append(result)
    (output/"index.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(f"Processed {len(files)} input(s); evidence written to {output.resolve()}")


if __name__=="__main__": main()
