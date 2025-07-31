from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Union

class AnalysisRequest(BaseModel):
    original_requirement: str
    regulation_document_name: str
    organizationId: str
    system_name: Optional[str] = ""
    objective: Optional[str] = ""
    req_id: Optional[str] = ""
    temperature: Optional[float] = Field(0.1, ge=0.0, le=1.0)

class PipelineRequest(AnalysisRequest):
    action: str = "startPipeline"

class Step1Analysis(BaseModel):
    req_id: str
    original_requirement: str
    incose_format: str
    ears_format: str
    incose_violations: List[str]
    ears_violations: List[str]
    requirement_pattern: str
    quality_rating: Union[str, int]
    feedback: str
    analysis_timestamp: str
    
    @field_validator('quality_rating')
    @classmethod
    def convert_quality_rating(cls, v):
        return str(v)

class RelevantPassage(BaseModel):
    section: str
    text: str
    relevance_score: str
    impact: str

class Step2Analysis(BaseModel):
    regulation_document: str
    relevant_passages: List[RelevantPassage]
    compliance_concerns: List[str]
    regulatory_keywords: List[str]
    analysis_timestamp: str

class Step3Analysis(BaseModel):
    final_requirement_ears: str
    final_requirement_incose: str
    compliance_status: str
    identified_conflicts: List[str]
    resolution_strategies: List[str]
    compliance_recommendations: List[str]
    regulatory_traceability: List[str]
    final_quality_rating: Union[str, int]
    enhancement_summary: str
    analysis_timestamp: str
    
    @field_validator('final_quality_rating')
    @classmethod
    def convert_final_quality_rating(cls, v):
        return str(v)

class AnalysisResult(BaseModel):
    status: str
    analysisJson: Step1Analysis
    analysisJson2: Step2Analysis
    analysisJson3: Step3Analysis
    processed_timestamp: str
