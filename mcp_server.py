from typing import Dict, Literal
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import base

# Name this MCP for clarity
mcp = FastMCP("ZoomWorkplaceMCP", log_level="ERROR")

# ---- In-memory "Zoom Workplace" datasets (mock data for your tutorial) ----
# Each collection is keyed by a string ID (e.g., meetingId, messageId, emailId, eventId).
zoom_data: Dict[str, Dict[str, Dict]] = {
    "meetings": {
        "987654321": {
            "topic": "Weekly Platform Sync",
            "agenda": "Zoom Developer platform updates",
            "start_time": "2025-09-08T15:00:00Z",
            "duration_minutes": 45,
            "host_user_id": "u_123",
            "participants": ["u_123", "u_456", "u_789"],
        },
        "123456789": {
            "topic": "Contact Center Deep Dive",
            "agenda": "Roadmap + integration patterns",
            "start_time": "2025-09-10T17:30:00Z",
            "duration_minutes": 60,
            "host_user_id": "u_555",
            "participants": ["u_555", "u_777"],
        },
    },
    "team_chat": {
        "msg_1001": {
            "channel": "devrel-internal",
            "sender_user_id": "u_456",
            "text": "Reminder: update SDK samples by Friday.",
            "timestamp": "2025-09-08T14:22:10Z",
        },
        "msg_1002": {
            "channel": "zoom-apps",
            "sender_user_id": "u_123",
            "text": "Draft blog on persistent participant IDs is ready.",
            "timestamp": "2025-09-08T16:10:03Z",
        },
    },
    "mail": {
        "email_2001": {
            "subject": "Zoom Apps Workshop Agenda",
            "from": "pm@zoom.us",
            "to": ["donte@zoom.us"],
            "received_at": "2025-09-07T19:45:00Z",
            "snippet": "Sharing the latest outline and owners...",
            "body": "Hi team,\n\nAttached is the draft agenda...\n",
        },
    },
    "calendar": {
        "event_3001": {
            "title": "DX Weekly Planning",
            "start": "2025-09-09T13:00:00Z",
            "end": "2025-09-09T13:30:00Z",
            "location": "Zoom Meeting",
            "organizer_user_id": "u_123",
            "attendees": ["u_123", "u_456", "u_789"],
        },
    },
}

ResourceType = Literal["meetings", "team_chat", "mail", "calendar"]

def _ensure_resource(resource_type: ResourceType, resource_id: str):
    if resource_type not in zoom_data:
        raise ValueError(f"Unknown resource_type '{resource_type}'. "
                         f"Use one of: meetings, team_chat, mail, calendar.")
    collection = zoom_data[resource_type]
    if resource_id not in collection:
        raise ValueError(f"{resource_type} item with ID '{resource_id}' not found.")
    return collection, collection[resource_id]

# ---------------------------- READ TOOL -------------------------------------
@mcp.tool(
    "read_zoom_resource",
    description="Read a Zoom Workplace item (meeting, chat message, email, or calendar event) by type and ID."
)

def read_zoom_resource(
    resource_type: ResourceType = Field(
        description="The Zoom dataset to read from. One of: 'meetings', 'team_chat', 'mail', 'calendar'."
    ),
    resource_id: str = Field(
        description="The ID of the item to read (e.g., meetingId, messageId, emailId, eventId)."
    ),
):
    """
    Returns the stored dict for the requested Zoom Workplace item.
    """
    _, item = _ensure_resource(resource_type, resource_id)
    return item

# ---------------------------- EDIT/UPSERT TOOL -------------------------------
@mcp.tool(
    "edit_zoom_resource",
    description="Edit or upsert a Zoom Workplace item. Returns the updated item."
)
def edit_zoom_resource(
    resource_type: ResourceType = Field(
        description="The Zoom dataset to write to. One of: 'meetings', 'team_chat', 'mail', 'calendar'."
    ),
    resource_id: str = Field(
        description="The ID of the item to edit or create (e.g., meetingId, messageId, emailId, eventId)."
    ),
    new_content: dict = Field(
        description="The replacement content for this item. Entire object is replaced."
    ),
    upsert: bool = Field(
        default=True,
        description="If True and the item does not exist, create it. If False, raise if not found."
    ),
):
    """
    Replaces the entire item content. For partial updates, add another tool that merges dicts.
    """
    if resource_type not in zoom_data:
        raise ValueError(f"Unknown resource_type '{resource_type}'. "
                         f"Use one of: meetings, team_chat, mail, calendar.")

    collection = zoom_data[resource_type]

    if resource_id not in collection and not upsert:
        raise ValueError(f"{resource_type} item with ID '{resource_id}' not found and upsert=False.")

    collection[resource_id] = new_content
    return collection[resource_id]


# ------------------------- RESOURCE DISCOVERY (LIST) -------------------------
@mcp.resource("res://resources", mime_type="application/json")
def list_zoom_resources():
    """
    List all Zoom Workplace resource IDs by type.
    Returns:
    {
      "meetings": ["123456789", "987654321"],
      "team_chat": ["msg_1001", "msg_1002"],
      "mail": ["email_2001"],
      "calendar": ["event_3001"]
    }
    """
    return {
        rtype: sorted(items.keys(), key=str)
        for rtype, items in zoom_data.items()
    }

# -------------------------- SINGLE RESOURCE (GET) ---------------------------
@mcp.resource("res://resources/{resource_type}/{resource_id}")
def get_zoom_resource(
    resource_type: ResourceType,
    resource_id: str,
):
    """
    Get a specific Zoom Workplace item by type and ID.
    Example paths:
      res://resources/meetings/987654321
      res://resources/team_chat/msg_1001
      res://resources/mail/email_2001
      res://resources/calendar/event_3001
    """
    if resource_type not in zoom_data:
        raise ValueError(f"Unknown resource_type '{resource_type}'. "
                         f"Use one of: meetings, team_chat, mail, calendar.")
    _, item = _ensure_resource(resource_type, resource_id)
    return item


# TODO: Write a prompt to rewrite a doc in markdown format
@mcp.prompt(
    name="format",
    description="Format a Zoom Workplace item as markdown for display.",
)
def format_document(
    resource_type: ResourceType = Field(
        description="The Zoom dataset to format. One of: 'meetings', 'team_chat', 'mail', 'calendar'."
    ),
    resource_id: str = Field(
        description="The ID of the item to format (e.g., meetingId, messageId, emailId, eventId)."
    ),
) -> list[dict]:
    prompt = f"""
Reformat the Zoom Workplace **{resource_type}** item below into clear Markdown for display.
Use headings, bullet points, and concise sections. Emojis are okay when tasteful.

Item identifier:
<resource>{resource_id}</resource>

After you produce the Markdown, call the `edit_zoom_resource` tool to save it back:
- resource_type = "{resource_type}"
- resource_id   = "{resource_id}"
- new_content   = {{ "markdown": "<your formatted markdown here>" }}

Return only the formatted Markdown in your assistant reply.
""".strip()

    # IMPORTANT: content must be a plain string for this MCP runtime
    return [{"role": "user", "content": prompt}]




# ---------------------------- RUN MCP SERVER ----------------------------
# TODO: Write a prompt to summarize a doc


if __name__ == "__main__":
    mcp.run(transport="stdio")
