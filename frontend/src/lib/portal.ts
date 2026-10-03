/**
 * The Public portal column (design: How the UI shows them): whether the image will appear on the museum's
 * public portal, combining the Object's sensitivity with the image's own publish setting. It is the BMU's
 * best estimate; the public pipelines make the final decision.
 */
import type {Row, TenantInfo} from '../types'

export interface Portal {
  k: 'pub' | 'hid';
  text: string;
  why: string;
}

export function portalOf(r: Row, tenant: TenantInfo): Portal {
  const h = tenant.handling.find((x) => x.id === r.handling)
  const header = tenant.publish.header
  if (h?.object !== 'none' && r.protected?.hides) {
    return {k: 'hid', text: 'Hidden: object sensitive',
      why: `The object is ${r.protected.reason}. The museum's public portal hides every image of this object, whatever the image's own setting.`}
  }
  const hidden = tenant.publish.invert ? r.restricted : !r.restricted
  if (hidden) return {k: 'hid', text: tenant.publish.invert ? 'Hidden: image restricted' : 'Hidden: image not published', why: `${header} is on for this image.`}
  return {k: 'pub', text: 'Public', why: 'Nothing on the object or the image keeps it off the public portal.'}
}
