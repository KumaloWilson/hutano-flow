// @vitest-environment jsdom
import React from 'react';
import {beforeAll,afterEach,it,expect,vi} from 'vitest';
import {render,screen,fireEvent,cleanup,waitFor} from '@testing-library/react';
import {ActionDialogProvider,useActionDialog,reasonField,choices} from './ActionDialog';

beforeAll(()=>{
  HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
  HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
});
afterEach(cleanup);
function Harness({done}:{done:(answer:unknown)=>void}){const ask=useActionDialog();return <button onClick={async()=>done(await ask({title:'Confirm safe action',fields:[reasonField,{name:'roles',label:'Roles',type:'checks',options:choices(['CLINICIAN','PHARMACY'])}]}))}>Open action</button>;}

it('cancel makes no command and restores focus to the invoking control',async()=>{
  const done=vi.fn();render(<ActionDialogProvider><Harness done={done}/></ActionDialogProvider>);
  screen.getByText('Open action').focus();fireEvent.click(screen.getByText('Open action'));
  fireEvent.click(await screen.findByText('Cancel'));await waitFor(()=>expect(done).toHaveBeenCalledWith(null));
  expect(document.activeElement).toBe(screen.getByText('Open action'));
});
it('returns structured reason and selected roles',async()=>{
  const done=vi.fn();render(<ActionDialogProvider><Harness done={done}/></ActionDialogProvider>);
  fireEvent.click(screen.getByText('Open action'));fireEvent.change(await screen.findByLabelText('Reason'),{target:{value:'Explicit synthetic staff decision'}});
  fireEvent.click(screen.getByLabelText('CLINICIAN'));fireEvent.click(screen.getByLabelText('PHARMACY'));
  fireEvent.click(screen.getByText('Confirm action'));await waitFor(()=>expect(done).toHaveBeenCalledWith({reason:'Explicit synthetic staff decision',roles:'CLINICIAN,PHARMACY'}));
});
it('Escape cancellation does not confirm an action',async()=>{
  const done=vi.fn();render(<ActionDialogProvider><Harness done={done}/></ActionDialogProvider>);
  fireEvent.click(screen.getByText('Open action'));fireEvent(await screen.findByRole('dialog'),new Event('cancel',{bubbles:false,cancelable:true}));
  await waitFor(()=>expect(done).toHaveBeenCalledWith(null));
});
