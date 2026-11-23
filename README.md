# alarm


## Architettura
- `entrypoints/` — solo punto di ingresso, carica config, costruisce oggetti
- `service/` — logica di dominio, riceve dipendenze iniettate (publisher, repository)
- `schema/` — contratti Pydantic, unica fonte di verità per i payload MQTT
- `model/` — tabelle SQLAlchemy, unica fonte di verità per il DB
- `publisher/`, `subscriber/` — trasporto MQTT puro, nessuna logica
- `repository/` — accesso al DB write-only

