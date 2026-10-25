import { useEffect } from 'react'
import '../../styles/room.css'

let users = 0

/** Put the page in the evening room (see styles/room.css) for as long as it is mounted. Nested callers share one room. */
export function useNightRoom() {
  useEffect(() => {
    users += 1
    document.documentElement.dataset.room = 'night'
    return () => {
      users -= 1
      if (users === 0) delete document.documentElement.dataset.room
    }
  }, [])
}
