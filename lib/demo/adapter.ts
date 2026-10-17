'use client'
import useSWR from 'swr'
import { toast } from 'sonner'
import { initialState } from './fixtures'
import { ApiError, type DemoState, type FrontendAdapter } from '../contracts'
let state:DemoState=structuredClone(initialState)
export const demoAdapter:FrontendAdapter={async getState(){return structuredClone(state)},async update(updater,expectedRevision){if(expectedRevision!==state.revision)throw new ApiError('conflict','This view changed. Please review it and try again.');const next=updater(structuredClone(state));state={...next,revision:state.revision+1};return structuredClone(state)}}
export function useDemo(){const {data=initialState,error,mutate,isLoading}=useSWR<DemoState>('career-kitchen-demo',()=>demoAdapter.getState(),{fallbackData:initialState,revalidateOnFocus:false});async function update(updater:(state:DemoState)=>DemoState,message?:string){try{await mutate(await demoAdapter.update(updater,data.revision),{revalidate:false});if(message)toast.success(message)}catch(e){toast.error(e instanceof Error?e.message:'Unable to update. Try again.');await mutate()}}return {data,error,isLoading,update}}
