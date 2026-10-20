"""Bound request parsing before FastAPI materializes JSON, not just after validation."""
import asyncio
import weakref
from fastapi import HTTPException
from starlette.responses import JSONResponse


class GenerationIntakeMiddleware:
    def __init__(self,app,max_bytes=10*1024*1024,concurrency=4):
        self.app,self.max_bytes,self.concurrency=app,max_bytes,concurrency
        self.slots=weakref.WeakKeyDictionary()

    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope.get('method')!='POST' or not scope.get('path','').startswith(('/api/v1/generation-operations','/api/v1/generation-imports')):
            return await self.app(scope,receive,send)
        loop=asyncio.get_running_loop()
        if loop not in self.slots:
            self.slots[loop]=asyncio.Semaphore(self.concurrency)
        slots=self.slots[loop]
        try:
            await asyncio.wait_for(slots.acquire(),2)
        except TimeoutError:
            return await JSONResponse({'detail':'طلبات استيراد أخرى قيد التجهيز؛ أعد المحاولة بالمفتاح نفسه'},status_code=429,headers={'Retry-After':'2'})(scope,receive,send)
        try:
            headers=dict(scope.get('headers',[]))
            length=headers.get(b'content-length',b'0')
            if not length.isdigit():
                return await JSONResponse({'detail':'Invalid Content-Length'},status_code=400)(scope,receive,send)
            if int(length)>self.max_bytes:
                return await JSONResponse({'detail':'الطلب يتجاوز 10MiB؛ استخدم الاستيراد المرحلي للملفات الكبيرة'},status_code=413)(scope,receive,send)
            received=0
            deadline=loop.time()+120
            async def bounded_receive():
                nonlocal received
                remaining=deadline-loop.time()
                if remaining<=0:
                    raise HTTPException(408,'انتهت مهلة رفع الطلب')
                try:
                    message=await asyncio.wait_for(receive(),min(30,remaining))
                except TimeoutError:
                    raise HTTPException(408,'توقف تدفق بيانات الطلب')
                if message['type']=='http.request':
                    received+=len(message.get('body',b''))
                    if received>self.max_bytes:
                        raise HTTPException(413,'الطلب يتجاوز الحد المسموح')
                return message
            await self.app(scope,bounded_receive,send)
        finally:
            slots.release()
