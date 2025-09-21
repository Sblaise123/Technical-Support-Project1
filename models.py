from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Float, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime

Base = declarative_base()

class Customer(Base):
    __tablename__ = "customers"
    
    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String(255), nullable=False)
    contact_name = Column(String(255))
    email = Column(String(255), unique=True, index=True)
    phone = Column(String(50))
    tier = Column(String(20), default="standard")  # standard, premium, enterprise
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Customer metrics
    total_tickets = Column(Integer, default=0)
    satisfaction_score = Column(Float, default=0.0)
    
    # Relationships
    tickets = relationship("Ticket", back_populates="customer")

class Agent(Base):
    __tablename__ = "agents"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True)
    level = Column(String(20), default="junior")  # junior, senior, lead, manager
    specializations = Column(JSON)  # List of specialization areas
    is_available = Column(Boolean, default=True)
    current_workload = Column(Integer, default=0)
    
    # Performance metrics
    total_tickets_resolved = Column(Integer, default=0)
    avg_resolution_time = Column(Float, default=0.0)
    customer_satisfaction = Column(Float, default=0.0)
    
    # Relationships
    assigned_tickets = relationship("Ticket", back_populates="agent")

class Ticket(Base):
    __tablename__ = "tickets"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    
    # Classification
    priority = Column(String(20), index=True)  # low, medium, high, critical, emergency
    category = Column(String(100), index=True)  # technical, billing, general, etc.
    urgency = Column(String(20))  # low, medium, high
    impact = Column(String(20))   # low, medium, high
    
    # Status tracking
    status = Column(String(50), default="open", index=True)  # open, in_progress, resolved, closed
    
    # Relationships
    customer_id = Column(Integer, ForeignKey("customers.id"))
    assigned_to = Column(Integer, ForeignKey("agents.id"))
    
    # Timestamps for SLA tracking
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    first_response_at = Column(DateTime(timezone=True))
    resolved_at = Column(DateTime(timezone=True))
    closed_at = Column(DateTime(timezone=True))
    
    # SLA targets
    first_response_due = Column(DateTime(timezone=True))
    resolution_due = Column(DateTime(timezone=True))
    
    # Escalation tracking
    escalated_at = Column(DateTime(timezone=True))
    escalation_reason = Column(Text)
    
    # Customer feedback
    satisfaction_rating = Column(Integer)  # 1-5 scale
    feedback_comment = Column(Text)
    
    # Relationships
    customer = relationship("Customer", back_populates="tickets")
    agent = relationship("Agent", back_populates="assigned_tickets")
    logs = relationship("TicketLog", back_populates="ticket")

class TicketLog(Base):
    __tablename__ = "ticket_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"))
    action = Column(String(100))  # created, updated, escalated, resolved, etc.
    description = Column(Text)
    created_by = Column(Integer, ForeignKey("agents.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    ticket = relationship("Ticket", back_populates="logs")

class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(100), index=True)
    tags = Column(JSON)  # List of tags
    
    # Metadata
    author_id = Column(Integer, ForeignKey("agents.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Usage metrics
    view_count = Column(Integer, default=0)
    helpful_votes = Column(Integer, default=0)
    not_helpful_votes = Column(Integer, default=0)
    
class SLATarget(Base):
    __tablename__ = "sla_targets"
    
    id = Column(Integer, primary_key=True, index=True)
    customer_tier = Column(String(20))  # standard, premium, enterprise
    priority = Column(String(20))
    first_response_hours = Column(Integer)  # Hours to first response
    resolution_hours = Column(Integer)     # Hours to resolution
    
class PerformanceMetrics(Base):
    __tablename__ = "performance_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"))
    date = Column(DateTime(timezone=True))
    
    # Daily metrics
    tickets_handled = Column(Integer, default=0)
    avg_response_time = Column(Float, default=0.0)
    avg_resolution_time = Column(Float, default=0.0)
    customer_satisfaction = Column(Float, default=0.0)
    sla_compliance_rate = Column(Float, default=0.0)