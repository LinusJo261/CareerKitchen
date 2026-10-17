export type Role = 'candidate' | 'employer'
export type Decision = 'interested' | 'passed'
export type Stage = 'Mutual interest' | 'Interviewing' | 'Offer' | 'Employment confirmed'
export interface CandidateProfile {id:string;name:string;title:string;location:string;skills:string[];summary:string;capacity:number;availability:string;experience:string;compensation:string;remote:string;privacy:boolean}
export interface Organization {id:string;name:string;verified:boolean;description:string}
export interface Vacancy {id:string;title:string;company:string;salary:string;location:string;arrangement:string;skills:string[];summary:string;deadline:string;verified:boolean;employerInterested:boolean;status:'Active'|'Draft';employmentType:string}
export interface Opportunity extends Vacancy {reason:string}
export interface MutualMatch {id:string;opportunityId:string;name:string;role:string;company:string;stage:Stage;updated:string}
export interface PactPolicy {id:string;role:string;version:string;compensation:string;arrangement:string;requirements:string[];evidence:string[];stages:string[];authority:string;expires:string;status:'Draft'|'Authorized'|'Revoked'}
export interface ConsentRecord {id:string;label:string;recipient:string;purpose:string;expires:string;granted:boolean}
export interface VerificationSummary {id:string;name:string;status:'Verified'|'Pending'|'Not shared';issuer:string}
export interface ClarificationRequest {id:string;title:string;description:string;action:string;status:'Pending'|'Approved'|'Rejected'}
export interface Interview {id:string;company:string;role:string;date:string;time:string;format:string;status:'Scheduled'|'Reschedule requested'}
export interface Offer {id:string;company:string;role:string;salary:string;deadline:string;status:'Awaiting response'|'Accepted'|'Declined'}
export interface Notification {id:string;title:string;description:string;read:boolean}
export interface Message {id:string;text:string;mine:boolean;time:string}
export interface Conversation {id:string;name:string;company:string;role:string;messages:Message[]}
export interface DemoState {profile:CandidateProfile;organization:Organization;opportunities:Opportunity[];candidates:CandidateProfile[];decisions:Record<string,Decision>;candidateDecisions:Record<string,Decision>;matches:MutualMatch[];interviews:Interview[];offers:Offer[];policy:PactPolicy;consents:ConsentRecord[];evidence:VerificationSummary[];clarifications:ClarificationRequest[];notifications:Notification[];conversations:Conversation[];team:{id:string;name:string;role:string}[];preferences:{email:boolean;digest:boolean};revision:number}
export type ApiErrorCode='unauthorized'|'forbidden'|'conflict'|'offline'|'expired'|'unknown'
export class ApiError extends Error {constructor(public code:ApiErrorCode,message:string){super(message)}}
export interface FrontendAdapter {getState():Promise<DemoState>;update(updater:(current:DemoState)=>DemoState,expectedRevision:number):Promise<DemoState>}
