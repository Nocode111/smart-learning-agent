from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, courses, knowledge_points, resources, questions
from app.routers import behaviors, qa, profiles, recommendations, exercise_generation, agent, agent_attachments, agent_chat_tasks, agent_local_files, agent_goals, agent_goal_guardian, agent_memories

from app.jobs.agent_goal_guardian_job import (
    start_goal_guardian_scheduler,
    shutdown_goal_guardian_scheduler,
)

app = FastAPI(title="Smart Learning Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(courses.router, prefix="/api/courses", tags=["courses"])
app.include_router(knowledge_points.router, prefix="/api/knowledge-points", tags=["knowledge-points"])
app.include_router(resources.router, prefix="/api/resources", tags=["resources"])
app.include_router(questions.router, prefix="/api/questions", tags=["questions"])
app.include_router(behaviors.router, prefix="/api/behaviors", tags=["behaviors"])
app.include_router(qa.router, prefix="/api/qa", tags=["qa"])
app.include_router(profiles.router, prefix="/api/profiles", tags=["profiles"])
app.include_router(recommendations.router, prefix="/api/recommendations", tags=["recommendations"])
app.include_router(exercise_generation.router, prefix="/api/exercise-generation", tags=["exercise-generation"])
app.include_router(agent.router, prefix="/api/agent", tags=["agent"])
app.include_router(agent_attachments.router, prefix="/api/agent/attachments", tags=["agent-attachments"])
app.include_router(agent_chat_tasks.router, prefix="/api/agent/chat-tasks", tags=["agent-chat-tasks"])
app.include_router(agent_memories.router, prefix="/api/agent/memories", tags=["agent-memories"])
app.include_router(agent_local_files.router, prefix="/api/agent/local-files", tags=["agent-local-files"])
app.include_router(agent_goals.router, prefix="/api/agent/goals", tags=["agent-goals"])
app.include_router(agent_goal_guardian.router, prefix="/api/agent/goals", tags=["agent-goal-guardian"])


@app.on_event("startup")
def startup_event():
    start_goal_guardian_scheduler()


@app.on_event("shutdown")
def shutdown_event():
    shutdown_goal_guardian_scheduler()


@app.get("/health")
def health_check():
    return {"status": "ok"}
