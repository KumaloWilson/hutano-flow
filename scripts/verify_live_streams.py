"""Check that idle SSE connections do not exhaust the API database pool."""
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import httpx


async def main():
    async with httpx.AsyncClient(base_url='http://localhost:8000',timeout=10) as client:
        response=await client.post('/api/v1/auth/login',json={'email':'clinician@demo.hutano.test','password':'DemoClinician1!'})
        response.raise_for_status()
        ready=asyncio.Queue()
        release=asyncio.Event()
        async def connected_stream():
            async with client.stream('GET','/api/v1/events') as response:
                response.raise_for_status()
                lines=response.aiter_lines()
                assert (await anext(lines)).startswith(': keepalive')
                await ready.put(True)
                await release.wait()
        tasks=[asyncio.create_task(connected_stream()) for _ in range(20)]
        try:
            for _ in tasks: await asyncio.wait_for(ready.get(),20)
            samples=[]
            for _ in range(3):
                started=time.monotonic()
                health=await client.get('/health')
                health.raise_for_status()
                elapsed=time.monotonic()-started
                assert health.json()['status']=='ok' and elapsed<5
                (await client.get('/api/v1/me')).raise_for_status()
                samples.append(round(elapsed,4))
                await asyncio.sleep(2.1)
        finally:
            release.set()
            await asyncio.gather(*tasks)
        Path('docs/evidence/live-streams.json').write_text(json.dumps({'status':'PASS','open_streams':20,
            'verified_at':datetime.now(timezone.utc).isoformat(),'health_response_seconds':samples,
            'held_open_seconds':6.3,'authenticated_requests_remained_available':True,
            'database_pool_remained_available':True},indent=2)+'\n')
        print('PASS: 20 simultaneous idle SSE streams; database-backed health remains responsive')


if __name__=='__main__': asyncio.run(main())
