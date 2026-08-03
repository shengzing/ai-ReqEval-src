"""集中化 harness 版本默认值常量，避免默认值字面量散落多处。

仅纯字符串常量，不依赖 registry，避免循环依赖。
Provider 类的 `version` 属性是自描述标识，保留字面值不改；
本模块只供"默认值兜底"路径引用（老数据缺字段、未注册版本回填等）。
"""

DEFAULT_AGENT_HARNESS_VERSION = "langgraph-v1"
DEFAULT_CONVERSATION_HARNESS_VERSION = "conversation-deepagents-v1"
