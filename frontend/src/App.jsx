import React, { useEffect, useState } from 'react';
import {
  Container,
  Row,
  Col,
  Card,
  Button,
  Spinner,
  Alert
} from 'react-bootstrap';
import { fetchSeries } from './api';

export default function App() {
  const [series, setSeries]   = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  useEffect(() => {
    fetchSeries()
      .then(data => setSeries(data))
      .catch(err  => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <Container className="py-4 text-center">
      <Spinner animation="border" role="status" />
    </Container>
  );

  if (error) return (
    <Container className="py-4">
      <Alert variant="danger">Error: {error}</Alert>
    </Container>
  );

  return (
    <Container className="py-4">
      <h1 className="mb-4 text-light">My Sonarr Library</h1>
      <Row xs={1} sm={2} md={3} lg={4} className="g-3">
        {series.map(s => (
          <Col key={s.id}>
            <Card bg="dark" text="light" className="h-100">
              <Card.Body>
                <Card.Title>{s.title}</Card.Title>
                <Card.Text>{s.seasons.length} seasons</Card.Text>
                <Button variant="outline-light">View Seasons</Button>
              </Card.Body>
            </Card>
          </Col>
        ))}
      </Row>
    </Container>
  );
}
