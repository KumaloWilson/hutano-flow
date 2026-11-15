import {expect,it} from "vitest";
import {canOperateService} from "./permissions";
import type {User} from "./types";
const user=(roles:string[])=>({id:"test",facility_id:"test",display_name:"Test",email:"test@example.invalid",roles,research_mode:true} satisfies User);
it("administrator and researcher cannot act as clinical staff",()=>{
  expect(canOperateService(user(["ADMIN"]),"consultation")).toBe(false);
  expect(canOperateService(user(["RESEARCHER"]),"pharmacy")).toBe(false);
});
it("pharmacy and clinical actions stay inside their assigned services",()=>{
  expect(canOperateService(user(["PHARMACY"]),"pharmacy")).toBe(true);
  expect(canOperateService(user(["PHARMACY"]),"consultation")).toBe(false);
  expect(canOperateService(user(["CLINICIAN"]),"pharmacy")).toBe(false);
  expect(canOperateService(user(["TRIAGE_NURSE"]),"triage")).toBe(true);
});
