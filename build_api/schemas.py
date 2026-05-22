from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .builder import validate_html_document


BuildTarget = Literal["android", "windows"]
JobStatus = Literal["queued", "running", "completed", "failed"]
AndroidPackageFormat = Literal["debug-apk", "apk", "aab"]
WindowsPackageFormat = Literal["msi", "zip", "exe"]
MenuPosition = Literal["top", "bottom"]


class HeaderOptions(BaseModel):
    enabled: bool = Field(True, description="Use native app header settings.")
    title: str | None = Field(None, max_length=120, description="Native header title. Defaults to app_name.")
    subtitle: str | None = Field(None, max_length=240, description="Optional subtitle for clients that support it.")
    background_color: str = Field("#111827", max_length=40)
    text_color: str = Field("#ffffff", max_length=40)


class MenuItem(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)
    href: str = Field("#", max_length=300)
    onclick: str | None = Field(None, max_length=500)


class MenuOptions(BaseModel):
    enabled: bool = Field(True, description="Create native menu commands with the submitted items.")
    position: MenuPosition = Field("top", description="Menu position relative to the submitted HTML.")
    items: list[MenuItem] = Field(default_factory=list)
    background_color: str = Field("#f8fafc", max_length=40)
    text_color: str = Field("#111827", max_length=40)


class AppIconOptions(BaseModel):
    source_path: str | None = Field(
        None,
        description="Internal path to uploaded or downloaded source image. Used to generate Android icons and Windows ICO.",
    )
    ico_path: str | None = Field(
        None,
        description="Internal path to uploaded or downloaded Windows icon source image.",
    )
    asset_dir: str | None = Field(
        None,
        description="Internal temporary asset directory deleted after the build.",
    )


class SourceBuildRequest(BaseModel):
    html: str = Field(
        ...,
        min_length=1,
        description="Full HTML document. Markdown code fences are allowed and stripped before validation.",
    )
    css: str = Field("", description="CSS code appended to the HTML.")
    js: str = Field("", description="JavaScript code appended to the HTML.")
    app_name: str = Field("api2app generated", min_length=1, max_length=80)
    bundle: str = Field("com.api2app.generated", min_length=3, max_length=120)
    version: str = Field("0.0.1", min_length=1, max_length=30)
    description: str = Field("Generated WebView application", max_length=300)
    header: HeaderOptions | None = Field(None, description="Native app header settings.")
    menu: MenuOptions | None = Field(None, description="Native app menu settings.")
    icon: AppIconOptions | None = Field(None, description="Application icon settings.")

    @field_validator("html")
    @classmethod
    def validate_html(cls, value: str) -> str:
        validate_html_document(value)
        return value


class AndroidBuildRequest(SourceBuildRequest):
    package_format: AndroidPackageFormat = Field(
        "debug-apk",
        description="Use debug-apk for direct phone installs, or apk/aab for release packaging.",
    )


class WindowsBuildRequest(SourceBuildRequest):
    package_format: WindowsPackageFormat = Field(
        "msi",
        description="Use msi or zip for Briefcase packaging; exe returns the built executable if Briefcase creates one.",
    )


class BuildAccepted(BaseModel):
    job_id: str
    status: JobStatus
    status_url: str
    download_url: str
    log_url: str


class JobStatusResponse(BaseModel):
    job_id: str
    target: BuildTarget
    status: JobStatus
    created_at: str
    updated_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    position: int | None = None
    artifact_name: str | None = None
    expires_at: str | None = None
    message: str | None = None
    status_url: str | None = None
    download_url: str | None = None
    log_url: str | None = None


class ActiveJobsResponse(BaseModel):
    jobs: list[JobStatusResponse]


def model_to_dict(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()
