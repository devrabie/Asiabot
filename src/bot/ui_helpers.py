import html
from typing import Optional, Sequence
from telegram import InlineKeyboardButton

FULL_WIDTH_SPACER = "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀"

# In-text animated custom emojis (RestrictedEmoji / verified catalog, always with fallback)
E_CROWN = '<tg-emoji emoji-id="5467406098367521267">👑</tg-emoji>'
E_DIAMOND = '<tg-emoji emoji-id="5471952986970267163">💎</tg-emoji>'
E_BOLT = '<tg-emoji emoji-id="5431449001532594346">⚡️</tg-emoji>'
E_STATS = '<tg-emoji emoji-id="5431577498364158238">📊</tg-emoji>'
E_USER = '<tg-emoji emoji-id="5373012449597335010">👤</tg-emoji>'
E_CARD = '<tg-emoji emoji-id="5422683699130933153">🪪</tg-emoji>'
E_ROCKET = '<tg-emoji emoji-id="5445284980978621387">🚀</tg-emoji>'
E_STAR = '<tg-emoji emoji-id="5435957248314579621">⭐️</tg-emoji>'
E_SUCCESS = '<tg-emoji emoji-id="5427009714745517609">✅</tg-emoji>'
E_ERROR = '<tg-emoji emoji-id="5465665476971471368">❌</tg-emoji>'
E_PENDING = '<tg-emoji emoji-id="5258419835922030550">⏳</tg-emoji>'
E_WARN = '<tg-emoji emoji-id="5258474669769497337">⚠️</tg-emoji>'
E_INFO = '<tg-emoji emoji-id="5258503720928288433">ℹ️</tg-emoji>'
E_GROWTH = '<tg-emoji emoji-id="5373001317042101552">📈</tg-emoji>'
E_FIRE = '<tg-emoji emoji-id="5420315771991497307">🔥</tg-emoji>'

# Button custom emoji IDs (from EMOJI_CATALOG.md)
BTN_ICON_RECHARGE = "5778412690384887021"     # 💰 money_bag
BTN_ICON_ACCOUNTS = "5764953177707258288"     # 👤 user_cog
BTN_ICON_ADD = "6050944273874951885"          # ➕ user_plus
BTN_ICON_PLANS = "5807868868886009920"        # 👑 crown_vip
BTN_ICON_ABOUT = "6021618194228187816"        # ❓ chat_question
BTN_ICON_REFRESH = "5845943483382110702"      # 🔄 arrow_retry
BTN_ICON_CHECK = "6050801358838177793"        # ✅ user_round_check
BTN_ICON_TRASH = "6039522349517115015"        # 🗑️ trash
BTN_ICON_BACK = "6039539366177541657"         # 🔙 back_arrow
BTN_ICON_CANCEL = "6051046090369670265"       # ✖️ user_round_x
BTN_ICON_HOME = "5807868868886009920"         # 🏠 home / vip
BTN_ICON_PHONE = "5771695636411847302"        # 📱 / 📢


def esc(value: object) -> str:
    """Safely escape dynamic values for Telegram HTML parse_mode."""
    if value is None:
        return ""
    return html.escape(str(value), quote=False)


def btn(
    text: str,
    callback_data: str,
    emoji_id: Optional[str] = None,
    style: Optional[str] = None,
) -> InlineKeyboardButton:
    """Create an InlineKeyboardButton with optional Bot API 9.4+ custom emoji & style."""
    api_kwargs = {}
    if emoji_id:
        api_kwargs["icon_custom_emoji_id"] = str(emoji_id)
    if style:
        api_kwargs["style"] = style
    if api_kwargs:
        return InlineKeyboardButton(text=text, callback_data=callback_data, api_kwargs=api_kwargs)
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def build_card(
    title: str,
    lines: Sequence[str],
    footer: Optional[str] = None,
    expandable_footer: bool = True,
) -> str:
    """Render a full-width Telegram Card UI in HTML format."""
    body = "\n".join(line for line in lines if line is not None)
    parts = [
        f"<b>{title}</b>",
        "",
        f"<blockquote>{body}\n{FULL_WIDTH_SPACER}</blockquote>",
    ]
    if footer:
        tag = "<blockquote expandable>" if expandable_footer else "<blockquote>"
        parts.extend(["", f"{tag}<i>{footer}</i></blockquote>"])
    return "\n".join(parts)
