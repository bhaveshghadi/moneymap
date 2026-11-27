'use client';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { Button } from '../primitives/Button';
import { Icon } from '../primitives/Icon';
import { CategoryGlyph } from '../primitives/CategoryGlyph';
import { DrawerHead } from './DrawerHead';

/** CAMS's free Consolidated Account Statement request page (covers CAMS and KFintech funds). */
export const CAMS_CAS_URL = 'https://www.camsonline.com/Investors/Statements/Consolidated-Account-Statement';

/** How to get a detailed CAS from CAMS, with a link that opens their page in a new tab. */
export function GetCasDialog({ onClose }: { onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Get your CAS" width={520}>
      <GetCasBody />
    </Dialog>
  );
}

function GetCasBody() {
  const close = useDialogClose();
  return (
    <>
      <DrawerHead
        title="Get your CAS"
        sub="Free, from CAMS — covers CAMS and KFintech funds"
        lead={<CategoryGlyph icon="file-text" color="indigo" size={42} />}
      />
      <div className="drawer-body">
        <ol style={{ paddingLeft: 18, lineHeight: 1.7, fontSize: 14, marginTop: 0 }}>
          <li>
            Open the{' '}
            <a href={CAMS_CAS_URL} target="_blank" rel="noreferrer">
              <b>CAMS CAS page</b>
            </a>{' '}
            (opens in a new tab).
          </li>
          <li>Statement type: <b>Detailed</b> (includes transactions).</li>
          <li>Period: <b>Specific period</b> from your first investment (or <b>Since inception</b>) to today.</li>
          <li>Folio listing: <b>Transacted folios and folios with balance</b>.</li>
          <li>Enter your email and PAN, and choose a <b>password</b>{' '}for the PDF — you&apos;ll type it in MoneyMap.</li>
          <li>
            The CAS arrives by email within minutes. Import it with <b>Import CAS</b>, or fetch it from Gmail in the Inbox (pick the CAMS mutual fund
            statement when fetching).
          </li>
        </ol>
        <div className="note info">
          <Icon name="info" size={15} />
          <span>
            Ask for a new CAS whenever you like (e.g. monthly): transactions already in MoneyMap are recognised and skipped. Fund prices update every
            evening from AMFI, so values stay current in between.
          </span>
        </div>
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Close</Button>
        <a className="btn btn-primary" href={CAMS_CAS_URL} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
          <Icon name="external-link" size={15} /> Open CAMS
        </a>
      </div>
    </>
  );
}
