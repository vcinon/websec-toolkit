from app.models.db import db


class Setting(db.Model):
    __tablename__ = "settings"

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text, nullable=False, default="")

    @classmethod
    def get(cls, key: str, default: str = "") -> str:
        row = db.session.get(cls, key)
        return row.value if row is not None else default

    @classmethod
    def set(cls, key: str, value: str) -> None:
        row = db.session.get(cls, key)
        if row is None:
            db.session.add(cls(key=key, value=value))
        else:
            row.value = value

    @classmethod
    def as_dict(cls) -> dict[str, str]:
        return {row.key: row.value for row in db.session.query(cls).all()}
