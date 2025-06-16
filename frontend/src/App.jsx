import React, { useEffect, useState } from 'react';
import { Container, Row, Col, Card, Button, Spinner, Alert, Badge } from 'react-bootstrap';
import { Link } from 'react-router-dom';
import './App.css';
import { fetchSeries, fetchMismatchCounts } from './api';
import Layout from './components/Layout';

export default function App() {
  const [series, setSeries]   = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  useEffect(() => {
    Promise.all([ fetchSeries(), fetchMismatchCounts() ])
      .then(([seriesData, mismatchData]) => {
        const lookup = mismatchData.reduce((acc, { seriesTitle, count }) => {
          acc[seriesTitle] = count;
          return acc;
        }, {});
        setSeries(
          seriesData.map(s => ({
            ...s,
            mismatchCount: lookup[s.title] || 0
          }))
        );
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Layout>
        <Container className="app-container text-center">
          <Spinner
            animation="border"
            role="status"
            style={{ color: 'var(--color-primary)' }}
          />
        </Container>
      </Layout>
    );
  }

  if (error) {
    return (
      <Layout>
        <Container className="app-container">
          <Alert variant="danger">Error: {error}</Alert>
        </Container>
      </Layout>
    );
  }

  return (
    <Layout>
      <Container fluid className="app-container">
        <div className="series-wrapper">
          <h1 className="page-title">My Sonarr Library</h1>
          <Row xs={1} sm={2} md={3} lg={4} className="g-3">
            {series.map(s => (
              <Col key={s.id}>
                <Card className="h-100 custom-card">
                  <Card.Body className="d-flex flex-column">
                    <Card.Title className="series-name">{s.title}</Card.Title>
                    <div className="mb-3">
                      <small className="seasons-text me-3">
                        {s.seasons.length || [].length} seasons
                      </small>
                      <Badge bg={s.mismatchCount === 0 ? 'success' : 'danger'}>
                        {s.mismatchCount} mismatch{s.mismatchCount !== 1 && 'es'}
                      </Badge>
                    </div>
                    <div className="mt-auto">
                      <Button
                        as={Link}
                        to={`/series/${encodeURIComponent(s.title)}`}
                        className="btn-primary-custom me-2"
                      >
                        View Seasons
                      </Button>
                      <Button
                        className="btn-accent"
                        onClick={() => window.location.reload()}
                      >
                        Refresh
                      </Button>
                    </div>
                  </Card.Body>
                </Card>
              </Col>
            ))}
          </Row>
        </div>
      </Container>
    </Layout>
  );
}
