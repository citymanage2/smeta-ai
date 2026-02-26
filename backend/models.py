from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from backend.database import Base

class Request(Base):
    __tablename__ = "requests"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    input_type = Column(String(100))  # ТЗ, ТЗ+Проект и т.д.
    uploaded_files = Column(JSON)  # [{name, size, format}]
    requested_outputs = Column(JSON)  # ["estimate", "list", "comparison"]
    status = Column(String(20), default="pending")  # pending, success, error
    claude_prompt = Column(Text, nullable=True)
    claude_response = Column(Text, nullable=True)
    output_files = Column(JSON, nullable=True)  # [{name, path, type}]
    error_message = Column(Text, nullable=True)
    user_comment = Column(Text, nullable=True)

    # Отношения
    output_files_rel = relationship("OutputFile", back_populates="request")


class OutputFile(Base):
    __tablename__ = "output_files"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("requests.id"))
    file_name = Column(String(255))
    file_path = Column(String(500))
    file_type = Column(String(50))  # excel_list, excel_estimate, pdf_comparison
    created_at = Column(DateTime, default=datetime.utcnow)

    # Отношения
    request = relationship("Request", back_populates="output_files_rel")
