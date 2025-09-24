from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Union, Literal, Dict, Any

class AnalysisRequest(BaseModel):
    original_requirement: str
    regulation_document_name: str
    organizationId: str
    system_name: Optional[str] = ""
    objective: Optional[str] = ""
    req_id: Optional[str] = ""
    temperature: Optional[float] = Field(0.1, ge=0.0, le=1.0)

class PipelineInput(BaseModel):
    input_name: str
    value: str

class PipelineStartParams(BaseModel):
    pipelineType: Optional[Literal['file-processing','requirement-analysis','requirement-analysis-reasoning','text-to-mermaid']] = Field(default=None, examples=["requirement-analysis"])
    requirement: Optional[str] = Field(default=None, examples=["The system shall ..."])
    fileNames: Optional[List[str]] = None
    systemName: Optional[str] = None
    objective: Optional[str] = None
    model_preference: Optional[str] = None
    temperature: Optional[float] = Field(default=0.1, ge=0.0, le=1.0, examples=[0.1])
    customPipelineInputs: Optional[List[PipelineInput]] = None
    savedItemId: Optional[str] = None
    organizationId: Optional[str] = None

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

# --- Requirements API Schemas ---

class RequirementCreateRequest(BaseModel):
    organizationId: str = Field(examples=["atoms-tech"])
    original_requirement: Optional[str] = Field(default=None, examples=["The system shall respond within 2 seconds"])
    systemName: Optional[str] = Field(default=None, examples=["Web App"])
    objective: Optional[str] = Field(default=None, examples=["Performance"])
    regulation_document_name: Optional[str] = Field(default=None, examples=["ISO-26262.pdf"])
    temperature: Optional[float] = Field(default=0.1, ge=0.0, le=1.0)

class RequirementRecord(BaseModel):
    req_id: str = Field(examples=["0001"])
    organizationId: str = Field(examples=["atoms-tech"])
    final_requirement_ears: str
    final_requirement_incose: str
    compliance_status: str
    final_quality_rating: Union[str, int]
    enhancement_summary: str
    created_at: str
    input_source: Literal['text','pdf']
    document_name: Optional[str] = None

class RequirementListResponse(BaseModel):
    items: List[RequirementRecord]
    total: int
    page: int
    pageSize: int
