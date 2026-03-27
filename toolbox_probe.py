import asyncio, json, re, httpx, sys
from vmos_cloud_api import VMOSCloudClient

PAD = 'ACP2509244LGV1MV'

async def run_adb(client, cmd, wait=7):
    r = await client.async_adb_cmd([PAD], cmd)
    tid = r['data'][0]['taskId']
    await asyncio.sleep(wait)
    t = await client.task_detail([tid])
    raw = t['data'][0]
    return raw.get('taskResult') or raw.get('errorMsg') or ''

async def screenshot(client, name):
    ss = await client.get_preview_image([PAD])
    url = ss['data'][0]['url']
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(url)
        with open(f'/tmp/{name}.jpg', 'wb') as f:
            f.write(r.content)
    print(f'Saved {name}: {len(r.content)} bytes')

async def main():
    client = VMOSCloudClient()
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'echo usage: toolbox_probe.py CMD'
    result = await run_adb(client, cmd)
    print(result)

if __name__ == '__main__':
    asyncio.run(main())
