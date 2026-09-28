"""Ein- und ausschaltbare Module.

Der Administrator schaltet Module unter *Module* um; der Zustand liegt in der Tabelle
``app_settings``. Solange ein Modul dort noch nie gespeichert wurde, gilt der Standardwert –
überschreibbar per Umgebungsvariable ``MODULE_<NAME>=true|false`` (z. B. ``MODULE_TEAM=false``).
"""
import os
from dataclasses import dataclass
from functools import wraps

from flask import abort, g, has_app_context

from .config import env_bool
from .extensions import db


@dataclass(frozen=True)
class Module:
    key: str
    label: str
    description: str
    category: str
    default: bool = True
    requires: tuple = ()
    env_default: str = None  # alte Umgebungsvariable, die als Standard dient


MODULES = {m.key: m for m in [
    Module("absences", "Abwesenheiten & Urlaub", "Urlaub, Krankheit, Freizeitausgleich usw. erfassen, Urlaubskonto. "
           "Bereits genehmigte Abwesenheiten zählen auch bei deaktiviertem Modul weiter in die Berechnung.",
           "Abwesenheiten"),
    Module("absence_approval", "Genehmigungs-Workflow",
           "Urlaub & Co. müssen vom Vorgesetzten genehmigt werden. Deaktiviert: Einträge gelten sofort.",
           "Abwesenheiten", requires=("absences",)),
    Module("email", "E-Mail-Benachrichtigungen",
           "Mail an Vorgesetzte bei neuen Anträgen und an Mitarbeiter bei der Entscheidung (SMTP_* muss gesetzt sein).",
           "Abwesenheiten", requires=("absences", "absence_approval")),
    Module("pause_button", "Pausen-Stempel", "Button „Pause“/„Weiter“ an der Stempeluhr. Deaktiviert: nur Kommen/Gehen.",
           "Zeiterfassung"),
    Module("stamp_notes", "Notizen beim Stempeln", "Freitext (z. B. Projekt/Tätigkeit) direkt an der Stempeluhr.",
           "Zeiterfassung"),
    Module("self_edit", "Zeiten selbst nachtragen", "Mitarbeiter dürfen eigene Zeiten nachtragen und korrigieren. "
           "Vorgesetzte und Admins dürfen das immer.", "Zeiterfassung", env_default="ALLOW_SELF_EDIT"),
    Module("terminal", "Stempelterminal", "Gemeinsames Gerät (z. B. Tablet am Eingang) zum Stempeln per "
           "Personalnummer und PIN – ohne Login. Terminals werden unter Admin > Terminals freigeschaltet.",
           "Zeiterfassung", default=False),
    Module("arbzg", "Arbeitszeitgesetz-Hinweise", "Warnungen bei zu kurzer Pause (6 h / 9 h) und mehr als 10 h pro Tag.",
           "Zeiterfassung"),
    Module("overtime", "Überstundenkonto", "Gesamtsaldo seit Erfassungsbeginn auf Startseite, Team-Übersicht, Berichten und PDF.",
           "Auswertung"),
    Module("team", "Team-Übersicht", "Live-Anwesenheit des Teams für Vorgesetzte und Admins.", "Auswertung"),
    Module("pdf_export", "PDF-Export", "Berichte als PDF herunterladen.", "Auswertung"),
    Module("csv_export", "CSV-/Excel-Export", "Berichte als CSV-Datei für Excel herunterladen.", "Auswertung"),
    Module("holidays", "Feiertage", "Feiertagsverwaltung und -import. Deaktiviert: Feiertage werden nicht berücksichtigt.",
           "Verwaltung"),
    Module("audit", "Änderungsprotokoll", "Protokolliert Korrekturen, Genehmigungen und Verwaltungsaktionen.",
           "Verwaltung"),
]}

CATEGORIES = ["Zeiterfassung", "Abwesenheiten", "Auswertung", "Verwaltung"]

_PREFIX = "module."
_CACHE = "_module_states"


def _default(module):
    value = env_bool(f"MODULE_{module.key.upper()}", None)
    if value is None and module.env_default:
        value = env_bool(module.env_default, None)
    return module.default if value is None else value


def _stored_states():
    from .models import Setting

    if has_app_context() and _CACHE in g:
        return g.get(_CACHE)
    rows = Setting.query.filter(Setting.setting_key.like(_PREFIX + "%")).all()
    states = {r.setting_key[len(_PREFIX):]: r.setting_value == "1" for r in rows}
    if has_app_context():
        setattr(g, _CACHE, states)
    return states


def own_state(key):
    """Eigener Schalter des Moduls, ohne Abhängigkeiten."""
    states = _stored_states()
    return states[key] if key in states else _default(MODULES[key])


def enabled(key):
    """Modul aktiv und alle benötigten Module ebenfalls aktiv?"""
    module = MODULES[key]
    return own_state(key) and all(enabled(dep) for dep in module.requires)


def set_state(key, value):
    from .models import Setting

    if key not in MODULES:
        raise KeyError(key)
    row = db.session.get(Setting, _PREFIX + key)
    if row is None:
        row = Setting(setting_key=_PREFIX + key)
        db.session.add(row)
    row.setting_value = "1" if value else "0"
    clear_cache()


def clear_cache():
    if has_app_context():
        g.pop(_CACHE, None)


def require_module(key):
    """Decorator: Route liefert 404, wenn das Modul deaktiviert ist."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not enabled(key):
                abort(404)
            return view(*args, **kwargs)
        return wrapper
    return decorator


def smtp_configured():
    return bool(os.environ.get("SMTP_HOST"))
