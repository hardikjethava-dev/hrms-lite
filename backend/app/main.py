from datetime import date, datetime
from typing import List, Literal, Optional

import os

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    func,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker


# ---------------------------------------------------------------------------
# Database setup (single-file, using env DATABASE_URL)
# ---------------------------------------------------------------------------

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(String(50), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    department = Column(String(100), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    attendance_records = relationship(
        "Attendance",
        back_populates="employee",
        cascade="all, delete-orphan",
    )


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("employee_id", "date", name="uq_employee_date"),)

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(
        Integer,
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date = Column(Date, nullable=False)
    status = Column(
        Enum("Present", "Absent", name="attendance_status"),
        nullable=False,
    )

    employee = relationship("Employee", back_populates="attendance_records")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class EmployeeBase(BaseModel):
    employee_id: str = Field(min_length=1, max_length=50)
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    department: Optional[str] = Field(default=None, max_length=100)


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeRead(EmployeeBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class AttendanceBase(BaseModel):
    employee_id: int
    date: date
    status: Literal["Present", "Absent"]


class AttendanceCreate(AttendanceBase):
    pass


class AttendanceRead(AttendanceBase):
    id: int

    class Config:
        from_attributes = True


class EmployeeUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[EmailStr] = None
    department: Optional[str] = Field(default=None, max_length=100)


class AttendanceUpdate(BaseModel):
    status: Literal["Present", "Absent"]


# ---------------------------------------------------------------------------
# FastAPI app and routes
# ---------------------------------------------------------------------------


app = FastAPI(title="HRMS Lite API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok"}


# Employee CRUD


@app.post(
    "/api/employees",
    response_model=EmployeeRead,
    status_code=status.HTTP_201_CREATED,
)
def create_employee(employee_in: EmployeeCreate, db: Session = Depends(get_db)):
    # Uniqueness checks
    existing_by_id = (
        db.query(Employee).filter(Employee.employee_id == employee_in.employee_id).first()
    )
    if existing_by_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Employee ID already exists",
        )

    existing_by_email = db.query(Employee).filter(Employee.email == employee_in.email).first()
    if existing_by_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already in use",
        )

    db_employee = Employee(
        employee_id=employee_in.employee_id,
        full_name=employee_in.full_name,
        email=employee_in.email,
        department=employee_in.department,
    )
    db.add(db_employee)
    db.commit()
    db.refresh(db_employee)
    return db_employee


@app.put(
    "/api/employees/{employee_id}",
    response_model=EmployeeRead,
)
def update_employee(
    employee_id: int,
    employee_in: EmployeeUpdate,
    db: Session = Depends(get_db),
):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    if employee_in.email and employee_in.email != employee.email:
        existing_by_email = db.query(Employee).filter(Employee.email == employee_in.email).first()
        if existing_by_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is already in use",
            )

    if employee_in.full_name is not None:
        employee.full_name = employee_in.full_name
    if employee_in.email is not None:
        employee.email = employee_in.email
    if employee_in.department is not None:
        employee.department = employee_in.department

    db.commit()
    db.refresh(employee)
    return employee


@app.get(
    "/api/employees",
    response_model=List[EmployeeRead],
)
def list_employees(
    skip: int = 0,
    limit: int = 100,
    id: Optional[int] = None,
    employee_id: Optional[str] = None,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    department: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Employee)

    if id is not None:
        query = query.filter(Employee.id == id)
    if employee_id is not None:
        query = query.filter(Employee.employee_id == employee_id)
    if full_name is not None:
        query = query.filter(Employee.full_name.ilike(f"%{full_name}%"))
    if email is not None:
        query = query.filter(Employee.email == email)
    if department is not None:
        query = query.filter(Employee.department == department)

    return (
        query.order_by(Employee.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@app.delete(
    "/api/employees/{employee_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_employee(employee_id: int, db: Session = Depends(get_db)):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )
    db.delete(employee)
    db.commit()


# Attendance CRUD


@app.post(
    "/api/attendance",
    response_model=AttendanceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_attendance(
    attendance_in: AttendanceCreate,
    db: Session = Depends(get_db),
):
    employee = db.query(Employee).filter(Employee.id == attendance_in.employee_id).first()
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    existing = (
        db.query(Attendance)
        .filter(
            Attendance.employee_id == attendance_in.employee_id,
            Attendance.date == attendance_in.date,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attendance already recorded for this employee and date",
        )

    db_attendance = Attendance(
        employee_id=attendance_in.employee_id,
        date=attendance_in.date,
        status=attendance_in.status,
    )
    db.add(db_attendance)
    db.commit()
    db.refresh(db_attendance)
    return db_attendance


@app.get(
    "/api/attendance",
    response_model=List[AttendanceRead],
)
def list_attendance(
    employee_id: Optional[int] = None,
    date_value: Optional[date] = None,
    status: Optional[Literal["Present", "Absent"]] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Attendance)

    if employee_id is not None:
        query = query.filter(Attendance.employee_id == employee_id)
    if date_value is not None:
        query = query.filter(Attendance.date == date_value)
    if status is not None:
        query = query.filter(Attendance.status == status)

    return query.order_by(Attendance.date.desc()).all()


@app.put(
    "/api/attendance/{attendance_id}",
    response_model=AttendanceRead,
)
def update_attendance(
    attendance_id: int,
    attendance_in: AttendanceUpdate,
    db: Session = Depends(get_db),
):
    attendance = db.query(Attendance).filter(Attendance.id == attendance_id).first()
    if not attendance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attendance record not found",
        )

    attendance.status = attendance_in.status

    db.commit()
    db.refresh(attendance)
    return attendance


@app.delete(
    "/api/attendance/{attendance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_attendance(attendance_id: int, db: Session = Depends(get_db)):
    attendance = db.query(Attendance).filter(Attendance.id == attendance_id).first()
    if not attendance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attendance record not found",
        )

    db.delete(attendance)
    db.commit()


@app.get(
    "/api/attendance/{employee_id}",
    response_model=List[AttendanceRead],
)
def list_attendance_for_employee(
    employee_id: int,
    db: Session = Depends(get_db),
):
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    return (
        db.query(Attendance)
        .filter(Attendance.employee_id == employee_id)
        .order_by(Attendance.date.desc())
        .all()
    )
