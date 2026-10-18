import Image from "next/image";
import Link from "next/link";
import { cn } from "@/lib/utils";
import careerKitchenLogo from "@/public/images/career-kitchen-logo.png";

/** A cream backing keeps the supplied green-and-gold logo clear on dark headers. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex size-10 shrink-0 items-center justify-center rounded-md bg-[#f7f2e8]",
        className,
      )}
    >
      <Image
        src={careerKitchenLogo}
        alt=""
        sizes="40px"
        className="size-full object-contain"
        loading="eager"
      />
    </span>
  );
}

export function Brand({
  compact = false,
  className,
}: {
  compact?: boolean;
  className?: string;
}) {
  return (
    <Link
      href="/"
      aria-label="Career Kitchen home"
      className={cn(
        "group flex w-fit items-center gap-2 rounded-sm sm:gap-2.5",
        className,
      )}
    >
      <BrandMark />
      {!compact && (
        <span className="font-serif text-lg leading-none tracking-tight whitespace-nowrap sm:text-[21px]">
          Career <span className="italic">Kitchen</span>
        </span>
      )}
    </Link>
  );
}

export function CompanyMark({
  name,
  className,
}: {
  name: string;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex size-11 shrink-0 items-center justify-center rounded-sm border border-foreground/15 bg-background font-serif text-xl italic text-primary",
        className,
      )}
    >
      {name.slice(0, 1)}
    </span>
  );
}
