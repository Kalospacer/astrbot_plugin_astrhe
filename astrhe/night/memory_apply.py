"""提交事务内应用日记草稿，不创建独立事务或提前提交。"""


async def apply_memory_edit(storage, payload, plan_date, run_id, now):
    return await storage.memory.apply_edit(payload, plan_date, run_id, now)
