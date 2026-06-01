from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

_security = HTTPBasic(auto_error=False)


def require_config_auth(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(_security),
) -> None:
    """Protegge le rotte di configurazione se server.auth_* è impostato.

    No-op se auth non è configurata (rotte aperte). Confronto in tempo costante.
    """
    cfg = request.app.state.config.server
    if not cfg.auth_username or not cfg.auth_password:
        return
    ok = (
        credentials is not None
        and secrets.compare_digest(credentials.username, cfg.auth_username)
        and secrets.compare_digest(credentials.password, cfg.auth_password)
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticazione richiesta.",
            headers={"WWW-Authenticate": "Basic"},
        )
