from __future__ import annotations

from pydantic import BaseModel


class AuthRegister(BaseModel):
    username: str
    password: str
    display_name: str = ""


class AuthLogin(BaseModel):
    username: str
    password: str


class PetCreate(BaseModel):
    name: str
    species: str = "cat"
    breed: str = ""
    age: str = ""
    avatar: str = ""
    bio: str = ""


class PetUpdate(BaseModel):
    name: str = ""
    species: str = ""
    breed: str = ""
    age: str = ""
    avatar: str = ""
    bio: str = ""


class CatVoiceAnnotation(BaseModel):
    user_label: str
    user_notes: str = ""


class TrainingCandidateReview(BaseModel):
    quality_status: str
    review_status: str
