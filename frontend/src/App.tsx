import { ErrorBoundary } from './components/Notice'
import { useRoute } from './lib/router'
import { Assessment } from './screens/Assessment'
import { InterviewList } from './screens/InterviewList'
import { Recording } from './screens/Recording'
import { Results } from './screens/Results'
import { Review } from './screens/Review'

export default function App() {
  const route = useRoute()
  // key: each screen and interview starts from fresh state
  let screen
  switch (route.screen) {
    case 'record': screen = <Recording key={`r${route.id}`} id={route.id} question={route.question} />; break
    case 'review': screen = <Review key={`v${route.id}`} id={route.id} />; break
    case 'assessment': screen = <Assessment key={`a${route.id}`} id={route.id} />; break
    case 'results': screen = <Results />; break
    default: screen = <InterviewList />
  }
  return <ErrorBoundary key={window.location.hash}>{screen}</ErrorBoundary>
}
