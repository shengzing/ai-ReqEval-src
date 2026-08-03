"""
SQLite数据库管理
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
import uuid

from .models import (
    EvaluationReport, DocumentInfo, MetricResult,
    ScenarioType, EvaluationMethod, EvaluationSession
)


class DatabaseManager:
    """数据库管理器"""

    def __init__(self, db_path: str = "data/history.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

    def _init_database(self):
        """初始化数据库表结构"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 评估记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS evaluations (
                    id TEXT PRIMARY KEY,
                    scenario TEXT NOT NULL,
                    method TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    user_input TEXT,
                    metrics TEXT,
                    summary TEXT,
                    recommendations TEXT,
                    visualizations TEXT,
                    raw_llm_output TEXT,
                    related_evaluation_id TEXT,
                    metadata TEXT,
                    FOREIGN KEY (related_evaluation_id) REFERENCES evaluations(id)
                )
            """)

            # 文档表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    evaluation_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content TEXT,
                    parsed_data TEXT,
                    upload_time DATETIME NOT NULL,
                    FOREIGN KEY (evaluation_id) REFERENCES evaluations(id)
                )
            """)

            # 会话表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    scenario TEXT NOT NULL,
                    method TEXT,
                    chat_history TEXT,
                    current_step TEXT,
                    state TEXT,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
            """)

            # 创建索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_evaluations_timestamp
                ON evaluations(timestamp DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_evaluations_method
                ON evaluations(method)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_evaluations_scenario
                ON evaluations(scenario)
            """)

            conn.commit()

    def save_evaluation(self, report: EvaluationReport) -> str:
        """保存评估报告"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 保存评估记录
            cursor.execute("""
                INSERT INTO evaluations (
                    id, scenario, method, timestamp, user_input, metrics,
                    summary, recommendations, visualizations, raw_llm_output,
                    related_evaluation_id, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                report.id,
                report.scenario.value,
                report.method.value,
                report.timestamp.isoformat(),
                json.dumps(report.user_input, ensure_ascii=False),
                json.dumps([{
                    "name": m.name,
                    "value": m.value,
                    "unit": m.unit,
                    "description": m.description,
                    "category": m.category
                } for m in report.metrics], ensure_ascii=False),
                report.summary,
                json.dumps(report.recommendations, ensure_ascii=False),
                json.dumps(report.visualizations, ensure_ascii=False),
                report.raw_llm_output,
                report.related_evaluation_id,
                json.dumps(report.metadata, ensure_ascii=False)
            ))

            # 保存文档
            for doc in report.documents:
                doc_id = str(uuid.uuid4())
                cursor.execute("""
                    INSERT INTO documents (
                        id, evaluation_id, filename, content, parsed_data, upload_time
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    doc_id,
                    report.id,
                    doc.filename,
                    doc.content,
                    json.dumps(doc.parsed_data, ensure_ascii=False) if doc.parsed_data else None,
                    doc.upload_time.isoformat()
                ))

            conn.commit()

        return report.id

    def get_evaluation(self, evaluation_id: str) -> Optional[EvaluationReport]:
        """获取评估报告"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 获取评估记录
            cursor.execute("""
                SELECT * FROM evaluations WHERE id = ?
            """, (evaluation_id,))
            row = cursor.fetchone()

            if not row:
                return None

            # 获取文档
            cursor.execute("""
                SELECT * FROM documents WHERE evaluation_id = ?
            """, (evaluation_id,))
            doc_rows = cursor.fetchall()

            documents = [
                DocumentInfo(
                    filename=doc["filename"],
                    content=doc["content"],
                    parsed_data=json.loads(doc["parsed_data"]) if doc["parsed_data"] else None,
                    upload_time=datetime.fromisoformat(doc["upload_time"])
                )
                for doc in doc_rows
            ]

            # 构建报告对象
            metrics_data = json.loads(row["metrics"])
            metrics = [
                MetricResult(
                    name=m["name"],
                    value=m["value"],
                    unit=m.get("unit"),
                    description=m.get("description"),
                    category=m.get("category")
                )
                for m in metrics_data
            ]

            report = EvaluationReport(
                id=row["id"],
                scenario=ScenarioType(row["scenario"]),
                method=EvaluationMethod(row["method"]),
                timestamp=datetime.fromisoformat(row["timestamp"]),
                user_input=json.loads(row["user_input"]),
                documents=documents,
                metrics=metrics,
                summary=row["summary"],
                recommendations=json.loads(row["recommendations"]),
                visualizations=json.loads(row["visualizations"]),
                raw_llm_output=row["raw_llm_output"],
                related_evaluation_id=row["related_evaluation_id"],
                metadata=json.loads(row["metadata"])
            )

            return report

    def list_evaluations(
        self,
        scenario: Optional[ScenarioType] = None,
        method: Optional[EvaluationMethod] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """列出评估记录（简要信息）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = "SELECT id, scenario, method, timestamp, summary FROM evaluations"
            conditions = []
            params = []

            if scenario:
                conditions.append("scenario = ?")
                params.append(scenario.value)

            if method:
                conditions.append("method = ?")
                params.append(method.value)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [
                {
                    "id": row["id"],
                    "scenario": row["scenario"],
                    "method": row["method"],
                    "timestamp": row["timestamp"],
                    "summary": row["summary"]
                }
                for row in rows
            ]

    def delete_evaluation(self, evaluation_id: str):
        """删除评估记录"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM documents WHERE evaluation_id = ?", (evaluation_id,))
            cursor.execute("DELETE FROM evaluations WHERE id = ?", (evaluation_id,))
            conn.commit()

    def save_session(self, session: EvaluationSession):
        """保存会话状态"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            chat_history_json = json.dumps([
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                    "metadata": msg.metadata
                }
                for msg in session.chat_history
            ], ensure_ascii=False)

            cursor.execute("""
                INSERT OR REPLACE INTO sessions (
                    session_id, scenario, method, chat_history,
                    current_step, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session.session_id,
                session.scenario.value,
                session.method.value if session.method else None,
                chat_history_json,
                session.current_step,
                json.dumps(session.state, ensure_ascii=False),
                session.created_at.isoformat(),
                datetime.now().isoformat()
            ))

            conn.commit()

    def get_session(self, session_id: str) -> Optional[EvaluationSession]:
        """获取会话状态"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()

            if not row:
                return None

            from .models import ChatMessage
            chat_history_data = json.loads(row["chat_history"])
            chat_history = [
                ChatMessage(
                    role=msg["role"],
                    content=msg["content"],
                    timestamp=datetime.fromisoformat(msg["timestamp"]),
                    metadata=msg.get("metadata", {})
                )
                for msg in chat_history_data
            ]

            return EvaluationSession(
                session_id=row["session_id"],
                scenario=ScenarioType(row["scenario"]),
                method=EvaluationMethod(row["method"]) if row["method"] else None,
                chat_history=chat_history,
                current_step=row["current_step"],
                state=json.loads(row["state"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"])
            )
