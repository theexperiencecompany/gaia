import { QRCodeSVG } from "qrcode.react";

interface ReferralQrCodeProps {
  url: string;
  size: number;
}

/** Dark modules on a light tile: phone cameras read inverted codes poorly. */
export function ReferralQrCode({ url, size }: ReferralQrCodeProps) {
  return (
    <div className="rounded-xl bg-zinc-100 p-2.5">
      <QRCodeSVG
        value={url}
        size={size}
        level="M"
        bgColor="transparent"
        fgColor="#18181b"
        title="Your invite link"
      />
    </div>
  );
}
