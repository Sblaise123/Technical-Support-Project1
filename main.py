from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import logging
from typing import List, Optional
import json

from database import engine, Base, get_db
from models import Ticket, Customer, KnowledgeBase, SLATarget, Agent
from schemas import (
    TicketCreate, TicketResponse, TicketUpdate, 
    CustomerCreate, KnowledgeBaseCreate, SLAReport
)
from services.ticket_classifier import TicketClassifier
from services.knowledge_searcher import KnowledgeSearcher
from services.notification_service import NotificationService
from services.sla_monitor import SLAMonitor
from services.analytics_service import AnalyticsService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="HelpDesk Pro - Technical Support System",
    description="Comprehensive ticket management with AI-powered support suggestions",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
ticket_classifier = TicketClassifier()
knowledge_searcher = KnowledgeSearcher()
notification_service = NotificationService()
sla_monitor = SLAMonitor()
analytics_service = AnalyticsService()

@app.on_event("startup")
async def startup_event():
    Base.metadata.create_all(bind=engine)
    logger.info("HelpDesk Pro started successfully")

@app.post("/api/tickets/", response_model=TicketResponse)
async def create_ticket(
    ticket: TicketCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    '''Create new support ticket with automatic classification and routing'''
    
    # Auto-classify ticket priority and category
    classification = ticket_classifier.classify_ticket(
        title=ticket.title,
        description=ticket.description,
        customer_tier=ticket.customer_tier
    )
    
    # Create ticket with classification
    db_ticket = Ticket(
        title=ticket.title,
        description=ticket.description,
        customer_id=ticket.customer_id,
        priority=classification['priority'],
        category=classification['category'],
        urgency=classification['urgency'],
        impact=classification['impact'],
        status='open',
        created_at=datetime.utcnow()
    )
    
    # Auto-assign based on category and agent availability
    assigned_agent = get_best_available_agent(db, classification['category'])
    if assigned_agent:
        db_ticket.assigned_to = assigned_agent.id
    
    db.add(db_ticket)
    db.commit()
    db.refresh(db_ticket)
    
    # Calculate SLA targets
    sla_targets = sla_monitor.calculate_sla_targets(db_ticket)
    db_ticket.first_response_due = sla_targets['first_response']
    db_ticket.resolution_due = sla_targets['resolution']
    db.commit()
    
    # Background tasks
    background_tasks.add_task(
        send_ticket_notifications, 
        db_ticket.id, 
        "created"
    )
    background_tasks.add_task(
        suggest_knowledge_articles, 
        db_ticket.id
    )
    background_tasks.add_task(
        update_customer_metrics, 
        ticket.customer_id
    )
    
    logger.info(f"Ticket #{db_ticket.id} created with priority {db_ticket.priority}")
    return db_ticket

@app.get("/api/tickets/", response_model=List[TicketResponse])
async def get_tickets(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    assigned_to: Optional[int] = None,
    sla_breach: Optional[bool] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    '''Retrieve tickets with advanced filtering for support agents'''
    
    query = db.query(Ticket)
    
    # Apply filters
    if status:
        query = query.filter(Ticket.status == status)
    if priority:
        query = query.filter(Ticket.priority == priority)
    if category:
        query = query.filter(Ticket.category == category)
    if assigned_to:
        query = query.filter(Ticket.assigned_to == assigned_to)
    
    # SLA breach filter
    if sla_breach is True:
        current_time = datetime.utcnow()
        query = query.filter(
            (Ticket.first_response_due < current_time) & 
            (Ticket.first_response_at.is_(None)) |
            (Ticket.resolution_due < current_time) & 
            (Ticket.resolved_at.is_(None))
        )
    
    tickets = query.offset(skip).limit(limit).all()
    return tickets

@app.put("/api/tickets/{ticket_id}", response_model=TicketResponse)
async def update_ticket(
    ticket_id: int,
    ticket_update: TicketUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    '''Update ticket with automatic SLA tracking and notifications'''
    
    db_ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not db_ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    # Store original status for comparison
    original_status = db_ticket.status
    
    # Update ticket fields
    for field, value in ticket_update.dict(exclude_unset=True).items():
        setattr(db_ticket, field, value)
    
    # Track status changes and SLA compliance
    if ticket_update.status and ticket_update.status != original_status:
        if ticket_update.status == 'in_progress' and not db_ticket.first_response_at:
            db_ticket.first_response_at = datetime.utcnow()
        elif ticket_update.status == 'resolved':
            db_ticket.resolved_at = datetime.utcnow()
    
    db_ticket.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_ticket)
    
    # Background notifications and updates
    background_tasks.add_task(
        send_ticket_notifications, 
        ticket_id, 
        "updated"
    )
    background_tasks.add_task(
        update_sla_metrics, 
        ticket_id
    )
    
    return db_ticket

@app.post("/api/tickets/{ticket_id}/escalate")
async def escalate_ticket(
    ticket_id: int,
    escalation_reason: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    '''Escalate ticket to higher tier support'''
    
    db_ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not db_ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    # Update priority and assign to senior agent
    original_priority = db_ticket.priority
    db_ticket.priority = escalate_priority(db_ticket.priority)
    db_ticket.escalated_at = datetime.utcnow()
    db_ticket.escalation_reason = escalation_reason
    
    # Find senior agent for escalation
    senior_agent = get_senior_agent_for_category(db, db_ticket.category)
    if senior_agent:
        db_ticket.assigned_to = senior_agent.id
    
    # Log escalation
    add_ticket_log(db, ticket_id, f"Escalated from {original_priority} to {db_ticket.priority}: {escalation_reason}")
    
    db.commit()
    
    # Notify management and customer
    background_tasks.add_task(escalate_notifications, ticket_id, escalation_reason)
    
    return {"message": f"Ticket escalated to {db_ticket.priority}", "new_priority": db_ticket.priority}

@app.get("/api/knowledge-base/search")
async def search_knowledge_base(
    query: str,
    category: Optional[str] = None,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    '''Search knowledge base with relevance scoring'''
    
    results = knowledge_searcher.search(
        query=query,
        category=category,
        limit=limit,
        db=db
    )
    
    return {
        "query": query,
        "results": results,
        "total_found": len(results)
    }

@app.post("/api/knowledge-base/", response_model=dict)
async def create_knowledge_article(
    article: KnowledgeBaseCreate,
    db: Session = Depends(get_db)
):
    '''Create new knowledge base article'''
    
    db_article = KnowledgeBase(
        title=article.title,
        content=article.content,
        category=article.category,
        tags=article.tags,
        author_id=article.author_id,
        created_at=datetime.utcnow()
    )
    
    db.add(db_article)
    db.commit()
    db.refresh(db_article)
    
    # Update search index
    knowledge_searcher.add_to_index(db_article)
    
    return {"message": "Knowledge article created", "id": db_article.id}

@app.get("/api/analytics/dashboard")
async def get_support_dashboard(
    days: int = 30,
    db: Session = Depends(get_db)
):
    '''Comprehensive support analytics dashboard'''
    
    dashboard_data = analytics_service.generate_dashboard(db, days)
    
    return {
        "period_days": days,
        "ticket_metrics": dashboard_data["tickets"],
        "sla_performance": dashboard_data["sla"],
        "agent_performance": dashboard_data["agents"],
        "customer_satisfaction": dashboard_data["csat"],
        "knowledge_base_usage": dashboard_data["kb_usage"],
        "trending_issues": dashboard_data["trends"]
    }

@app.get("/api/reports/sla", response_model=SLAReport)
async def generate_sla_report(
    start_date: str,
    end_date: str,
    category: Optional[str] = None,
    db: Session = Depends(get_db)
):
    '''Generate detailed SLA performance report'''
    
    sla_report = sla_monitor.generate_report(
        db=db,
        start_date=datetime.fromisoformat(start_date),
        end_date=datetime.fromisoformat(end_date),
        category=category
    )
    
    return sla_report

# Helper functions for ticket management
def get_best_available_agent(db: Session, category: str):
    '''Find best available agent for ticket category'''
    agents = db.query(Agent).filter(
        Agent.is_available == True,
        Agent.categories.contains(category)
    ).order_by(Agent.current_workload).limit(1).all()
    
    return agents[0] if agents else None

def escalate_priority(current_priority: str) -> str:
    '''Escalate ticket priority'''
    priority_levels = ["low", "medium", "high", "critical", "emergency"]
    current_index = priority_levels.index(current_priority)
    if current_index < len(priority_levels) - 1:
        return priority_levels[current_index + 1]
    return current_priority

async def send_ticket_notifications(ticket_id: int, action: str):
    '''Send notifications for ticket updates'''
    # This would integrate with email/Slack/SMS services
    pass

async def suggest_knowledge_articles(ticket_id: int):
    '''Suggest relevant knowledge articles for ticket'''
    # AI-powered article suggestions
    pass