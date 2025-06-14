import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Container, Table, Spinner, Alert, Button } from 'react-bootstrap';

export default function SeriesDetail() {
  const { seriesTitle } = useParams();
  const [episodes, setEpisodes] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`/api/series/${encodeURIComponent(seriesTitle)}/episodes`)
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(setEpisodes)
      .catch(err => setError(err));
  }, [seriesTitle]);

  if (!episodes) return (
    <Container className="py-4 text-center">
      <Spinner animation="border" role="status" />
    </Container>
  );
  if (error) return (
    <Container className="py-4">
      <Alert variant="danger">Error: {error}</Alert>
      <Button as={Link} to="/">← Back</Button>
    </Container>
  );

  return (
    <Container fluid className="py-4">
      <Button as={Link} to="/" variant="outline-light" className="mb-3">
        ← Back
      </Button>
      <Table striped hover responsive variant="dark">
        <thead>
          <tr>
            <th>Match?</th>
            <th>Code</th>
            <th>Expected Title</th>
            <th>Actual Title</th>
            <th>Confidence</th>
          </tr>
        </thead>
        <tbody>
          {episodes.map(ep => (
            <tr key={ep.key}>
              <td>{ep.matches ? '✅' : '❌'}</td>
              <td>{ep.code}</td>
              <td>{ep.expectedTitle}</td>
              <td>{ep.actualTitle}</td>
              <td>{ep.confidence}</td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Container>
  );
}

