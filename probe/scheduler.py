import asyncio, time

class Scheduler:
    """Monotonic, evenly spread rounds with bounded concurrency."""
    def __init__(self, targets, interval, concurrency, attempt):
        self.targets, self.interval, self.sem, self.attempt = targets, interval, asyncio.Semaphore(concurrency), attempt
    async def run_round(self, started=None):
        started = time.monotonic() if started is None else started
        delay = self.interval / max(1, len(self.targets))
        results = []
        for i, target in enumerate(self.targets):
            due = started + i * delay
            await asyncio.sleep(max(0, due - time.monotonic()))
            if self.sem.locked():
                results.append(await self.attempt(target, skipped='capacity_exhausted'))
            else:
                results.append(asyncio.create_task(self._run(target)))
        return [await r if isinstance(r, asyncio.Task) else r for r in results]
    async def _run(self, target):
        async with self.sem: return await self.attempt(target)
