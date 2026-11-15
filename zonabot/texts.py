"""User-facing Spanish texts and keyboards."""
from datetime import datetime

MENU_CHANGE_LINK = "Cambiar link de búsqueda"
MENU_TOGGLE = "Activar/Desactivar notificaciones"
MENU_FORCE = "Forzar búsqueda ahora"
MENU_INFO = "Mostrar información"

DISABLE_CALLBACK = "off"
LEGACY_DISABLE_CALLBACK_PREFIX = "toggle_"

WELCOME = (
    "Hola! Soy un bot para ayudarte a encontrar publicaciones en Zonaprop",
    "Vos te armás una búsqueda con todas las opciones y filtros que quieras y me pasás el link. "
    "Yo me encargo de chequear si hay publicaciones nuevas y te aviso si encuentro algo",
    "Podés mandarme un link directamente o usar el menú para interactuar conmigo",
)
START_FIRST = "Usá /start para inicializar el bot ;)"
ASK_FOR_LINK = "Dale, mandame el link de la búsqueda que quieras seguir"
INVALID_LINK = (
    "El link que mandaste no es válido. Fijate que sea un link de Zonaprop. "
    "Si pensás que es un error avisale a Jan :P"
)
NEED_LINK_FIRST = "Primero necesito un link de búsqueda. Podés mandarme uno directamente o usar el menú"
FORCE_ACK = "Estoy mirando las publicaciones, dame un segundo..."
NOT_UNDERSTOOD = (
    "Mmmm, no entendí. Mejor usá el menú para interactuar conmigo",
    "No soy muy inteligente igual así que si tenés algún problema avisale a Jan :)",
)
DISABLED_CALLBACK_ANSWER = "Listo, desactivé las notificaciones"

SUMMARY_TAIL = "Voy a enviarte mensajes cuando aparezcan publicaciones nuevas."
FETCH_FAILED = "No pude cargar la búsqueda en este momento. Probá de nuevo en unos minutos."
BASELINE_STILL_TRYING = "Todavía no pude cargar tu búsqueda, sigo intentando. Te aviso cuando esté lista."
CHECKS_RECOVERED = "Ya pude volver a revisar tu búsqueda, todo funciona de nuevo."
ADMIN_RECOVERED = "ZonaBot: las búsquedas volvieron a funcionar."


def main_menu_keyboard():
    return {
        "keyboard": [[MENU_CHANGE_LINK], [MENU_TOGGLE], [MENU_FORCE], [MENU_INFO]],
        "resize_keyboard": True,
    }


def disable_button():
    return {"inline_keyboard": [[{"text": "Desactivar notificaciones", "callback_data": DISABLE_CALLBACK}]]}


def link_set(url):
    return f"Listo, ahora el link de búsqueda es:\n{url}"


def notifications_state(enabled):
    return f"Las notificaciones ahora están {'activadas' if enabled else 'desactivadas'}"


def info(notifications, last_scan, original_url):
    return (
        f"- Notificaciones: {'Activadas' if notifications else 'Desactivadas'}\n"
        f"- Última búsqueda: {last_scan or 'Nunca'}\n"
        f"- Link de búsqueda: {original_url or 'No configurado'}"
    )


def baseline_summary(total):
    if total == 0:
        return f"Por ahora no encontré publicaciones que se hayan subido hoy. \n{SUMMARY_TAIL}"
    if total == 1:
        return f"Encontré 1 publicación que se subió hoy. {SUMMARY_TAIL}"
    return f"Encontré {total} publicaciones que se subieron hoy. {SUMMARY_TAIL}"


def digest(remaining, search_url):
    noun = "publicación nueva más" if remaining == 1 else "publicaciones nuevas más"
    return f"Y hay {remaining} {noun}. Miralas en Zonaprop:\n{search_url}"


def forced_nothing_new(total):
    return f"No hay publicaciones nuevas desde la última búsqueda. Tu búsqueda tiene {total} publicaciones de hoy."


def forced_while_disabled(total):
    return (
        f"Tu búsqueda tiene {total} publicaciones de hoy. "
        "Las notificaciones están desactivadas, activalas para que te avise de las nuevas."
    )


def checks_failing(last_scan):
    try:
        since = f" desde el {datetime.strptime(last_scan, '%Y-%m-%d %H:%M:%S'):%d/%m %H:%M}"
    except (TypeError, ValueError):
        since = ""
    return (
        f"No estoy pudiendo revisar tu búsqueda{since}. "
        "Sigo intentando y te aviso cuando vuelva a funcionar."
    )


def admin_failures(count, error):
    return f"ZonaBot: fallaron {count} búsquedas seguidas. Último error: {error}"
