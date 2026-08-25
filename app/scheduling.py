"""Cadenze di aggiornamento allineate all'orologio.

Singola fonte di verità per *quando* aggiornare dati e display, usata dal
loop e-ink ([app/main.py]) e dall'anteprima web.

Politica (valori di default, configurabili via ``refresh`` in config):

- **Display**: la griglia dei repaint è bihoraria e allineata alle ore pari
  (``00:00``, ``02:00``, …, ``22:00``), così da coincidere con la finestra di
  previsione bioraria del meteo. Un repaint costa 20-30 s di lampeggio del
  pannello, quindi la cadenza è dettata da *quanto spesso il contenuto cambia
  davvero*, non da quanto spesso si potrebbe aggiornare.
- **Fascia di quiete**: di notte (``23:00``–``06:00``) i push sono sospesi;
  l'e-ink mantiene l'immagine a costo zero. Sopravvivono solo i momenti
  elencati in ``allowed_ticks``: l'inizio della fascia (``23:00``) e la
  mezzanotte, necessaria per il cambio di data.
- **Calendario**: il *poll* di rete resta ogni quarto d'ora, ma è disaccoppiato
  dal push: si ridipinge solo se cambia il contenuto del calendario, e non più
  di una volta ogni ``min_push_interval_minutes`` così che una raffica di
  modifiche dal telefono si fonda in un solo repaint.

I confini sono calcolati sull'ora locale (``datetime.now()``), coerente con il
fuso del dispositivo.

Nota: ``in_quiet_hours`` ha un doppio uso — sospende i push *e* seleziona la
variante notturna del frame (senza i dati istantanei del meteo, vedi
:func:`app.weather.provider.strip_instant_fields`). Un frame che resta a
schermo per sei ore non può mostrare una temperatura letta all'inizio della
notte.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import RefreshConfig

# ---------------------------------------------------------------------------
# Default della politica (rispecchiati da RefreshConfig in app/config.py)
# ---------------------------------------------------------------------------

DISPLAY_INTERVAL_MINUTES: int = 120
CALENDAR_POLL_MINUTES: int = 15
MIN_PUSH_INTERVAL_MINUTES: int = 20

# Auto-reload dell'anteprima nel browser. Deliberatamente *scollegato* dalla
# cadenza del pannello: ricaricare una pagina non costa un repaint e-ink, e
# legarlo alla griglia bihoraria congelerebbe l'anteprima per due ore.
WEB_REFRESH_SECONDS: int = 300

# TTL della cache eventi dell'aggregator. Segue il poll del calendario, non la
# cadenza display, per lo stesso motivo di cui sopra.
CALENDAR_CACHE_TTL_SECONDS: int = CALENDAR_POLL_MINUTES * 60


@dataclass(frozen=True)
class RefreshPolicy:
    """Politica di refresh risolta, con gli orari già parsati.

    Costruita una volta da :meth:`from_config` e passata al loop e-ink. Tutti i
    metodi sono puri e dipendono solo dal ``datetime`` passato, così che il
    comportamento sia verificabile senza congelare l'orologio.
    """

    display_interval_minutes: int = DISPLAY_INTERVAL_MINUTES
    calendar_poll_minutes: int = CALENDAR_POLL_MINUTES
    min_push_interval_minutes: int = MIN_PUSH_INTERVAL_MINUTES
    quiet_start: time | None = None
    quiet_end: time | None = None
    allowed_ticks: tuple[time, ...] = field(default_factory=tuple)

    # ------------------------------------------------------------------
    # Costruzione
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, cfg: "RefreshConfig") -> "RefreshPolicy":
        """Costruisce la politica dalla sezione ``refresh`` della config."""
        quiet = cfg.quiet_hours
        return cls(
            display_interval_minutes=cfg.display_interval_minutes,
            calendar_poll_minutes=cfg.calendar_poll_minutes,
            min_push_interval_minutes=cfg.min_push_interval_minutes,
            quiet_start=quiet.start_time if quiet.enabled else None,
            quiet_end=quiet.end_time if quiet.enabled else None,
            allowed_ticks=quiet.allowed_tick_times if quiet.enabled else (),
        )

    # ------------------------------------------------------------------
    # Fascia di quiete
    # ------------------------------------------------------------------

    def in_quiet_hours(self, moment: datetime) -> bool:
        """True se *moment* cade nella fascia di quiete notturna.

        L'inizio è incluso e la fine esclusa, così che il push di apertura
        (``23:00``) sia già "notturno" — è il primo frame che resterà a schermo
        senza aggiornamenti — mentre quello di chiusura (``06:00``) sia già
        diurno e mostri di nuovo la banda meteo completa.

        La fascia attraversa la mezzanotte (``23:00`` → ``06:00``), quindi il
        confronto è disgiuntivo quando ``start > end``.
        """
        if self.quiet_start is None or self.quiet_end is None:
            return False
        t = moment.time().replace(second=0, microsecond=0)
        if self.quiet_start <= self.quiet_end:
            return self.quiet_start <= t < self.quiet_end
        return t >= self.quiet_start or t < self.quiet_end

    # ------------------------------------------------------------------
    # Tick del display
    # ------------------------------------------------------------------

    def is_display_tick(self, moment: datetime) -> bool:
        """True se *moment* è un momento in cui il pannello va ridipinto.

        Tre regole, in ordine:

        1. gli orari di ``allowed_ticks`` valgono **sempre**, dentro o fuori dai
           confini della fascia. Il sigillo è l'ultimo repaint prima della notte
           e la mezzanotte serve al cambio di data: entrambi devono avvenire al
           proprio orario, altrimenti spostare l'inizio della fascia li farebbe
           sparire in silenzio. (La lista è vuota a fascia disattivata, quindi
           questa regola non aggiunge nulla quando non c'è una notte da gestire.)
        2. dentro la fascia, nient'altro: è il senso della quiete;
        3. fuori, i confini della griglia display.
        """
        if moment.second or moment.microsecond:
            return False
        if self._matches_allowed_tick(moment):
            return True
        if self.in_quiet_hours(moment):
            return False
        return self._minutes_since_midnight(moment) % self.display_interval_minutes == 0

    def is_night_frame(self, moment: datetime) -> bool:
        """True se il frame stampato a *moment* deve omettere i dati istantanei.

        Vale dentro la fascia di quiete e sugli orari di ``allowed_ticks``, che
        sono notturni per definizione anche quando cadono fuori dai confini: il
        sigillo e la mezzanotte esistono per la notte, e i loro frame restano a
        schermo per ore. Con una fascia ``00:30``–``06:00`` il frame di mezzanotte
        cade tecnicamente fuori banda ma sopravvive fino alle 06:00 — mostrarvi
        una temperatura letta a mezzanotte è esattamente ciò che la variante
        notturna deve impedire.

        Vedi :func:`app.weather.provider.strip_instant_fields` per cosa viene
        rimosso e perché la strip bioraria invece resta.
        """
        return self.in_quiet_hours(moment) or self._matches_allowed_tick(moment)

    def _matches_allowed_tick(self, moment: datetime) -> bool:
        """True se *moment* coincide (ora e minuto) con un orario consentito.

        Il confronto ignora i secondi: il loop valuta il confine per cui si è
        svegliato, ma i consumatori della variante notturna usano l'ora reale,
        che arriva sempre con un po' di ritardo.
        """
        return any(
            moment.hour == at.hour and moment.minute == at.minute
            for at in self.allowed_ticks
        )

    def next_display_tick(self, now: datetime) -> datetime:
        """Ritorna il prossimo tick display strettamente successivo a *now*.

        I candidati sono il prossimo confine di griglia utile (saltando quelli
        soppressi dalla fascia di quiete) e la prossima occorrenza di ciascun
        ``allowed_ticks``; vince il più vicino. Con quiete ``23:00``–``06:00`` e
        tick consentiti ``23:00``/``00:00`` la sequenza risultante è
        ``… 20:00 · 22:00 · 23:00 · 00:00 · 06:00 · 08:00 …``.
        """
        step = timedelta(minutes=self.display_interval_minutes)
        candidates: list[datetime] = []

        # Prossimo confine di griglia non soppresso. Il numero di iterazioni è
        # limitato a una giornata: oltre, la fascia di quiete coprirebbe l'intero
        # arco delle 24 ore e nessun confine di griglia sarebbe mai valido.
        grid = self._floor_to_grid(now) + step
        for _ in range(int(timedelta(days=1) / step) + 1):
            if self.is_display_tick(grid):
                candidates.append(grid)
                break
            grid += step

        # Prossima occorrenza degli orari consentiti in fascia di quiete.
        for at in self.allowed_ticks:
            cand = now.replace(
                hour=at.hour, minute=at.minute, second=0, microsecond=0
            )
            if cand <= now:
                cand += timedelta(days=1)
            if self.is_display_tick(cand):
                candidates.append(cand)

        if not candidates:
            # Configurazione degenere (quiete su 24 ore senza tick consentiti):
            # si torna alla griglia nuda per non fermare mai il loop.
            return self._floor_to_grid(now) + step
        return min(candidates)

    # ------------------------------------------------------------------
    # Poll del calendario
    # ------------------------------------------------------------------

    def next_poll_tick(self, now: datetime) -> datetime:
        """Ritorna il prossimo confine di poll calendario successivo a *now*."""
        minutes = self.calendar_poll_minutes
        floored = now.replace(
            minute=(now.minute // minutes) * minutes, second=0, microsecond=0
        )
        return floored + timedelta(minutes=minutes)

    def next_wake(self, now: datetime) -> datetime:
        """Ritorna il momento in cui il loop deve risvegliarsi.

        È il minimo fra il prossimo tick display e il prossimo poll del
        calendario, così che il loop dorma sempre fino al primo evento utile
        senza polling attivo.

        I poll che cadono nella fascia di quiete vengono saltati: lì un push
        guidato dal calendario è comunque sospeso, quindi il fetch di rete
        sarebbe lavoro a vuoto. Con i default il loop dorme da mezzanotte alle
        06:00 senza toccare la rete, e i dati vengono riletti al tick di
        riapertura.
        """
        display = self.next_display_tick(now)
        poll = self.next_poll_tick(now)
        if self.in_quiet_hours(poll):
            return display
        return min(display, poll)

    def push_allowed(self, moment: datetime) -> bool:
        """True se un push guidato dal calendario è consentito a *moment*.

        Fuori dalla fascia di quiete sempre; dentro, mai — una modifica fatta
        alle 02:00 attende il tick di riapertura, perché nessuno sta guardando
        e il repaint costa un lampeggio.
        """
        return not self.in_quiet_hours(moment)

    # ------------------------------------------------------------------
    # Helper privati
    # ------------------------------------------------------------------

    @staticmethod
    def _minutes_since_midnight(moment: datetime) -> int:
        return moment.hour * 60 + moment.minute

    def _floor_to_grid(self, moment: datetime) -> datetime:
        """Ritorna il confine di griglia display corrente (secondi azzerati)."""
        total = self._minutes_since_midnight(moment)
        aligned = (total // self.display_interval_minutes) * self.display_interval_minutes
        return moment.replace(
            hour=aligned // 60, minute=aligned % 60, second=0, microsecond=0
        )
