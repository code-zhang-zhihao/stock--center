from pydantic import BaseModel, Field


class SkillInfo(BaseModel):
    code: str
    display_name: str
    family: str
    capabilities: list[str]
    key_env: str | None = None
    runtime: str
    args_style: str
    timeout_seconds: int | None = None
    entrypoint: str


class SkillRunRequest(BaseModel):
    query: str = Field(min_length=1)
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=10, ge=1, le=100)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    extra: dict | None = None


class SkillCredential(BaseModel):
    key_id: int
    secret_value: str
    key_name: str | None = None
    secret_fingerprint: str | None = None


class SkillRunFile(BaseModel):
    path: str
    name: str
    size: int
    content_type: str | None = None


class SkillRunResult(BaseModel):
    success: bool
    skill_code: str
    trace_id: str
    query: str
    exit_code: int | None = None
    latency_ms: int | None = None
    normalized: dict = Field(default_factory=dict)
    stdout_json: dict | list | None = None
    stdout_text: str | None = None
    files: list[SkillRunFile] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


class SkillChainResult(BaseModel):
    success: bool
    capability: str
    trace_id: str
    query: str
    resolved_skill: str | None = None
    attempted_skills: list[str] = Field(default_factory=list)
    results: list[SkillRunResult] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)
