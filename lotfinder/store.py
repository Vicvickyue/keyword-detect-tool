import json
import sqlite3


class Store:
    def __init__(self, path):
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY, source TEXT, name TEXT, suffix TEXT,
                kind TEXT, depth INTEGER, status TEXT, error TEXT DEFAULT '', total INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS hits (
                file_id INTEGER, rule TEXT, keyword TEXT, total INTEGER,
                PRIMARY KEY (file_id, rule, keyword));
            CREATE TABLE IF NOT EXISTS evidence (
                id INTEGER PRIMARY KEY, file_id INTEGER, rule TEXT, keyword TEXT, payload TEXT);
            CREATE INDEX IF NOT EXISTS evidence_lookup ON evidence(file_id,rule,keyword);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        """)
        self.pending = 0

    def meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))
        self.db.commit()

    def metadata(self):
        return {r["key"]: json.loads(r["value"]) for r in self.db.execute("SELECT * FROM meta")}

    def add_file(self, source, name, suffix, kind, depth):
        cur = self.db.execute("INSERT INTO files(source,name,suffix,kind,depth,status) VALUES(?,?,?,?,?,?)",
                              (source, name, suffix, kind, depth, "处理中"))
        return cur.lastrowid

    def finish(self, file_id, status, error=""):
        self.db.execute("UPDATE files SET status=?,error=? WHERE id=?", (status, error, file_id))
        self.db.commit()

    def record(self, file_id, matches, payload):
        for (rule, keyword), count in matches.items():
            self.db.execute("""INSERT INTO hits VALUES(?,?,?,?) ON CONFLICT(file_id,rule,keyword)
                               DO UPDATE SET total=total+excluded.total""", (file_id, rule, keyword, count))
            saved = self.db.execute("SELECT COUNT(*) FROM evidence WHERE file_id=? AND rule=? AND keyword=?",
                                    (file_id, rule, keyword)).fetchone()[0]
            if saved < 5:
                data = dict(payload, occurrences=count)
                self.db.execute("INSERT INTO evidence(file_id,rule,keyword,payload) VALUES(?,?,?,?)",
                                (file_id, rule, keyword, json.dumps(data, ensure_ascii=False)))
        self.db.execute("UPDATE files SET total=total+? WHERE id=?", (sum(matches.values()), file_id))
        self.pending += 1
        if self.pending >= 250:
            self.db.commit()
            self.pending = 0

    def files(self):
        return self.db.execute("SELECT * FROM files ORDER BY id")

    def hits(self, file_id):
        return self.db.execute("SELECT * FROM hits WHERE file_id=? ORDER BY rule,keyword", (file_id,))

    def evidence(self, file_id, rule, keyword):
        return [json.loads(r[0]) for r in self.db.execute(
            "SELECT payload FROM evidence WHERE file_id=? AND rule=? AND keyword=? ORDER BY id",
            (file_id, rule, keyword))]

    def summary(self):
        return dict(self.db.execute("""SELECT COUNT(*) AS files,
            COALESCE(SUM(total),0) AS total,
            COALESCE(SUM(total>0),0) AS matched,
            COALESCE(SUM(status NOT IN ('完成','已展开','分卷附件')),0) AS incomplete,
            COALESCE(SUM(status='已展开'),0) AS archives FROM files""").fetchone())

    def close(self):
        self.db.commit()
        self.db.close()

    def report_summary(self):
        return dict(self.db.execute("""SELECT
            COALESCE(SUM(status='完成' AND kind!='archive'),0) AS completed_content,
            COALESCE(SUM(status='完成' AND kind!='archive' AND total=0),0) AS unmatched,
            COALESCE(SUM(kind='archive' OR status='已展开'),0) AS containers,
            COALESCE(SUM(status='分卷附件'),0) AS volume_parts FROM files""").fetchone())
