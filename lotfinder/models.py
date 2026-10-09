from dataclasses import dataclass, field
from pathlib import Path


RULE_NAMES = {
    "product_lot": "产品 Lot ID",
    "npw_lot": "NPW Lot ID",
    "product": "Product ID",
    "foup": "Foup ID",
    "eqid": "EQID",
    "layer": "Layer_Step",
}
DICT_RULES = ("product", "eqid", "layer")


@dataclass
class ScanConfig:
    sources: list[Path]
    output: Path
    dictionaries: dict[str, Path] = field(default_factory=dict)
    enabled: list[str] = field(default_factory=lambda: list(RULE_NAMES))
    case_sensitive: bool = True
    whole_id: bool = True
    header_row: int = 1
    max_depth: int = 10
    max_file_bytes: int = 2 * 1024**3
    max_expanded_bytes: int = 10 * 1024**3
    max_files: int = 10000
    archive_timeout: int = 180
    seven_zip: str = ""

    def validate(self):
        if not self.sources or any(not p.exists() for p in self.sources):
            raise ValueError("请选择存在的待检索文件或目录。")
        if self.header_row < 0 or self.max_depth < 5:
            raise ValueError("表头行不能为负数；压缩深度至少为 5。")
        if not any(r in RULE_NAMES for r in self.enabled):
            raise ValueError("请至少启用一条规则。")
        if min(self.max_file_bytes, self.max_expanded_bytes, self.max_files, self.archive_timeout) <= 0:
            raise ValueError("资源限制必须大于零。")


class Cancelled(Exception):
    pass


class LimitExceeded(Exception):
    pass
