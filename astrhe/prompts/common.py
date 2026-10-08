"""夜间人格与任务格式的共同边界。"""


def persona_system(persona_prompt: str) -> str:
    return (
        "【你的人格】\n"
        + (persona_prompt or "采用 AstrBot 默认人格")
        + "\n\n【人格说明】人格决定你是谁、在意什么、对每个人的感情和说话口吻；"
        "这里任务的输出长度和格式，以下面的任务要求为准，不受人格里关于说话长短、格式的要求约束。"
    )
