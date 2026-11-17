export type Place = "desk" | "your_desk" | "rack" | "pantry" | "door";
export type Pose = "type" | "read" | "run" | "web" | "work" | "ask" | "smoke" | "coffee" | "leave";
export interface Look { body: number; hair: number; shirt: number; accessory: number }
export interface Avatar { key: string; sessionId: string; identity: string; seat: number; look: Look; place: Place; pose: Pose; deskTile: { x: number; y: number }; name: string; app: string; project: string }
export interface Cluster { project: string; origin: { x: number; y: number }; desks: { x: number; y: number }[] }
export interface Office { width: number; height: number; clusters: Cluster[]; yourDesk: { x: number; y: number }; rack: { x: number; y: number }; pantry: { x: number; y: number }; door: { x: number; y: number }; avatars: Avatar[] }
