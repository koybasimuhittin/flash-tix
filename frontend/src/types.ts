// Response shapes from the API contracts.

export type Role = "customer" | "organizer";

export interface User {
  id: number;
  email: string;
  name: string;
  role: Role;
}

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
}

export interface EventSummary {
  id: number;
  title: string;
  venue: string;
  city: string;
  starts_at: string;
  sales_open_at: string;
  min_price_cents: number;
  capacity: number;
}

export interface Section {
  code: string;
  name: string;
  price_cents: number;
  rows: number;
  seats_per_row: number;
  sort_order: number;
}

export interface EventDetail extends EventSummary {
  description: string;
  sections: Section[];
}

export interface Availability {
  event_id: number;
  server_time: string;
  sold: string[];
  held: string[];
  my_holds: string[];
}

export interface Hold {
  event_id: number;
  seats: string[];
  expires_at: string;
}

export interface BookingSeat {
  seat_id: string;
  section_name: string;
  price_cents: number;
}

export interface Booking {
  id: string;
  event_id: number;
  event_title: string;
  event_starts_at: string;
  venue: string;
  city: string;
  status: string;
  seat_count: number;
  total_price_cents: number;
  created_at: string;
  seats: BookingSeat[];
  ticket_ready: boolean;
}

export interface EventStats {
  event_id: number;
  sold: number;
  held: number;
}

export interface SectionIn {
  code: string;
  name: string;
  price_cents: number;
  rows: number;
  seats_per_row: number;
}

export interface EventIn {
  title: string;
  description: string;
  venue: string;
  city: string;
  starts_at: string;
  sales_open_at: string;
  sections: SectionIn[];
}
