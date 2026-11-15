"use client";
import { createContext, useContext, useEffect, useRef, useState, ReactNode, FormEvent } from "react";

type Field = { name: string; label: string; type?: "text" | "textarea" | "number" | "datetime-local" | "time" | "select" | "checks"; value?: string; options?: {value:string;label:string}[]; required?: boolean; min?: number; max?: number; step?: string };
type Question = { title: string; description?: string; submit?: string; fields?: Field[] };
type Answer = Record<string,string>;
const Context = createContext<(q:Question)=>Promise<Answer|null>>(()=>Promise.resolve(null));
export const useActionDialog = () => useContext(Context);
export const choices = (values:string[]) => values.map(value=>({value,label:value.replaceAll("_"," ")}));
export const reasonField: Field = {name:"reason",label:"Reason",type:"textarea",required:true,min:5,max:500};

export function ActionDialogProvider({children}:{children:ReactNode}) {
  const [question,setQuestion]=useState<Question|null>(null);
  const resolve=useRef<((a:Answer|null)=>void)|null>(null);
  const dialog=useRef<HTMLDialogElement>(null);
  const previousFocus=useRef<HTMLElement|null>(null);
  function close(answer:Answer|null) { dialog.current?.close();resolve.current?.(answer);resolve.current=null;setQuestion(null);previousFocus.current?.focus(); }
  useEffect(()=>{if(question)dialog.current?.showModal();},[question]);
  useEffect(()=>()=>{resolve.current?.(null);},[]);
  function ask(q:Question) { resolve.current?.(null);previousFocus.current=document.activeElement as HTMLElement;setQuestion(q);return new Promise<Answer|null>(r=>{resolve.current=r;}); }
  function submit(e:FormEvent<HTMLFormElement>) {e.preventDefault();const data=new FormData(e.currentTarget);const result=Object.fromEntries(data.entries()) as Answer;question?.fields?.filter(f=>f.type==="checks").forEach(f=>{result[f.name]=data.getAll(f.name).join(",");});close(result);}
  return <Context.Provider value={ask}>{children}{question&&<dialog ref={dialog} className="action-dialog" aria-labelledby="action-title" onCancel={e=>{e.preventDefault();close(null);}}><form onSubmit={submit}>
    <h2 id="action-title">{question.title}</h2>{question.description&&<p>{question.description}</p>}
    {question.fields?.map(f=>f.type==="checks"?<fieldset key={f.name}><legend>{f.label}</legend>{f.options?.map(o=><label className="checkbox" key={o.value}><input type="checkbox" name={f.name} value={o.value} defaultChecked={f.value?.split(",").includes(o.value)}/>{o.label}</label>)}</fieldset>:<label key={f.name}>{f.label}{f.type==="select"?<select name={f.name} defaultValue={f.value} required={f.required}>{f.options?.map(o=><option key={o.value} value={o.value}>{o.label}</option>)}</select>:f.type==="textarea"?<textarea name={f.name} defaultValue={f.value} required={f.required} minLength={f.min} maxLength={f.max} rows={3}/>:<input name={f.name} type={f.type||"text"} defaultValue={f.value} required={f.required} min={f.min} max={f.max} step={f.step} maxLength={f.type==="text"?f.max:undefined}/>}</label>)}
    <div className="row-actions"><button type="button" className="secondary" onClick={()=>close(null)}>Cancel</button><button className="primary">{question.submit||"Confirm action"}</button></div>
  </form></dialog>}</Context.Provider>;
}
