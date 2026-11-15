import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, formatTime, commandKey } from "./api";

describe("formatTime", () => {
  it("returns a placeholder for missing timestamps", () => expect(formatTime(null)).toBe("—"));
  it("formats server UTC values for Africa/Harare", () => expect(formatTime("2026-10-24T08:00:00Z")).toContain("10:00"));
});

afterEach(()=>vi.unstubAllGlobals());

describe('safe command client',()=>{
  it('creates secure UUIDs on HTTP LAN browsers without randomUUID',()=>{
    const getRandomValues=crypto.getRandomValues.bind(crypto);
    vi.stubGlobal('crypto',{getRandomValues});
    const first=commandKey(),second=commandKey();
    expect(first).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
    expect(first).not.toBe(second);
  });
  it('reuses the idempotency key after an uncertain network result',async()=>{
    const calls:RequestInit[]=[];
    vi.stubGlobal('fetch',vi.fn(async (_url,options)=>{calls.push(options);if(calls.length===1)throw new Error('Connection lost');return new Response(JSON.stringify({ok:true}),{status:201});}));
    const options={method:'POST',body:JSON.stringify({synthetic_flag:true})};
    await expect(api('/test/retry',options)).rejects.toThrow('Connection lost');
    await api('/test/retry',options);
    expect(new Headers(calls[0].headers).get('Idempotency-Key')).toBe(new Headers(calls[1].headers).get('Idempotency-Key'));
    expect(calls[1].credentials).toBe('include');
  });
  it('does not enqueue an offline clinical mutation',async()=>{
    vi.stubGlobal('navigator',{onLine:false});
    const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
    await expect(api('/test/triage',{method:'POST',body:'{}'})).rejects.toThrow('Offline');
    expect(fetch).not.toHaveBeenCalled();
  });
  it('surfaces conflicts with request IDs instead of silently retrying',async()=>{
    vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({error:'Refresh the current version',request_id:'trace-123'}),{status:409})));
    try {await api('/test/conflict',{method:'POST',body:'{}'});throw new Error('Expected rejection');}
    catch(error) {expect(error).toBeInstanceOf(ApiError);expect((error as ApiError).requestId).toBe('trace-123');}
  });
});

