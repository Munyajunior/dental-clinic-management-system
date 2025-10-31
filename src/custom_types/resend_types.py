from typing import TypedDict, List, Optional, Union


class ResendAttachment(TypedDict, total=False):
    filename: str
    content: Union[str, bytes]
    path: Optional[str]


class ResendSendParams(TypedDict, total=False):
    from_: str
    to: List[str]
    subject: str
    html: str
    text: str
    cc: Optional[List[str]]
    bcc: Optional[List[str]]
    reply_to: Optional[str]
    attachments: Optional[List[ResendAttachment]]
