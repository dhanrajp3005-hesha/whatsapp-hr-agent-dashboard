from pydantic import BaseModel, EmailStr, Field


class SessionIn(BaseModel):
    access_token: str
    refresh_token: str


class SmtpSettingsIn(BaseModel):
    smtp_host: str = Field(min_length=1)
    smtp_port: int = Field(gt=0, lt=65536)
    smtp_username: str = Field(min_length=1)
    smtp_password: str = Field(min_length=1)
    from_email: EmailStr


class CommunitySelectIn(BaseModel):
    community_name: str = Field(min_length=1)


class MailContentIn(BaseModel):
    # Empty string resets that field back to the app default.
    subject: str = ""
    body: str = ""
