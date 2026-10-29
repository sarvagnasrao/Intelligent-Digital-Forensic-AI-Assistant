import sys
sys.path.insert(0, '.')

from main import *
import asyncio
import json

async def test():
    req = ExamineRequest(
        case_id=1, 
        evidence_id=1, 
        image_path='/mnt/e/Users/sarva/Downloads/SCHARDT.001', 
        operation='full_examination', 
        parameters={}
    )
    result = await examine(req)
    print(json.dumps(result.model_dump(), indent=2))

asyncio.run(test())